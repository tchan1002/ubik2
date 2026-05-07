"""
iMessage Database Reader

Provides read-only access to the macOS iMessage database (chat.db).
Handles Apple's timestamp format and provides safe schema validation.
"""

import sqlite3
import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path


# Custom Exceptions
class iMessageDatabaseError(Exception):
    """Base exception for iMessage database operations."""
    pass


class SchemaValidationError(iMessageDatabaseError):
    """Raised when the database schema is invalid or incomplete."""
    pass


class DatabaseAccessError(iMessageDatabaseError):
    """Raised when Full Disk Access is not granted or database is inaccessible."""
    pass


class TimestampConverter:
    """
    Converts Apple's timestamp format to Unix timestamps and Python datetime objects.

    Apple stores timestamps as nanoseconds since 2001-01-01 00:00:00 UTC (the Cocoa epoch),
    while Unix timestamps use seconds since 1970-01-01 00:00:00 UTC.
    """

    # Seconds between Unix epoch (1970-01-01) and Apple epoch (2001-01-01)
    APPLE_EPOCH_OFFSET = 978307200

    @classmethod
    def apple_to_unix(cls, apple_ts: int) -> float:
        """
        Convert Apple timestamp to Unix timestamp.

        Args:
            apple_ts: Nanoseconds since 2001-01-01 00:00:00 UTC

        Returns:
            Unix timestamp (seconds since 1970-01-01 00:00:00 UTC)
        """
        if apple_ts is None or apple_ts == 0:
            return 0.0
        return (apple_ts / 1e9) + cls.APPLE_EPOCH_OFFSET

    @classmethod
    def apple_to_datetime(cls, apple_ts: int) -> Optional[datetime.datetime]:
        """
        Convert Apple timestamp to Python datetime object.

        Args:
            apple_ts: Nanoseconds since 2001-01-01 00:00:00 UTC

        Returns:
            datetime object in local timezone, or None if timestamp is 0/None
        """
        if apple_ts is None or apple_ts == 0:
            return None
        unix_ts = cls.apple_to_unix(apple_ts)
        return datetime.datetime.fromtimestamp(unix_ts)


class iMessageDatabaseReader:
    """
    Read-only interface to the macOS iMessage database.

    Provides safe access to chat.db with schema validation and proper error handling.
    Never writes to the database.

    Usage:
        with iMessageDatabaseReader() as reader:
            handles = reader.get_all_handles()
            messages = reader.get_messages_for_handle(handle_id=123)
    """

    # Default location of iMessage database on macOS
    DEFAULT_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"

    # Required tables for schema validation
    REQUIRED_TABLES = {"message", "handle", "chat", "chat_message_join", "attachment"}

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the database reader.

        Args:
            db_path: Path to chat.db. Defaults to ~/Library/Messages/chat.db

        Raises:
            DatabaseAccessError: If database file doesn't exist or can't be accessed
        """
        self.db_path = db_path or self.DEFAULT_DB_PATH
        self.connection: Optional[sqlite3.Connection] = None

        if not self.db_path.exists():
            raise DatabaseAccessError(
                f"Database not found at {self.db_path}. "
                "Ensure Full Disk Access is granted in System Settings → "
                "Privacy & Security → Full Disk Access."
            )

    def __enter__(self) -> "iMessageDatabaseReader":
        """Context manager entry - opens database connection."""
        try:
            # Open in read-only mode with URI to prevent any writes
            uri = f"file:{self.db_path}?mode=ro"
            self.connection = sqlite3.connect(uri, uri=True)
            self.connection.row_factory = sqlite3.Row  # Enable column access by name

            # Validate schema on connection
            self.validate_schema()

            return self
        except sqlite3.OperationalError as e:
            raise DatabaseAccessError(
                f"Cannot access database at {self.db_path}. "
                "Full Disk Access may not be granted. "
                f"Error: {e}"
            ) from e

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - closes database connection."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def validate_schema(self) -> None:
        """
        Validate that all required tables exist in the database.

        Raises:
            SchemaValidationError: If any required table is missing
        """
        if not self.connection:
            raise iMessageDatabaseError("No active database connection")

        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )

        existing_tables = {row[0] for row in cursor.fetchall()}
        missing_tables = self.REQUIRED_TABLES - existing_tables

        if missing_tables:
            raise SchemaValidationError(
                f"Database schema is incomplete. Missing tables: {', '.join(sorted(missing_tables))}"
            )

    def get_all_handles(self) -> List[Dict[str, Any]]:
        """
        Retrieve all contact handles (phone numbers and email addresses).

        Returns:
            List of handle records with keys: ROWID, id, country, service

        Example:
            [
                {
                    "ROWID": 1,
                    "id": "+12025551234",
                    "country": "us",
                    "service": "iMessage"
                },
                ...
            ]
        """
        if not self.connection:
            raise iMessageDatabaseError("No active database connection")

        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT ROWID, id, country, service
            FROM handle
            ORDER BY ROWID
            """
        )

        return [dict(row) for row in cursor.fetchall()]

    def get_messages_for_handle(
        self,
        handle_id: int,
        include_reactions: bool = False,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch all messages for a specific contact handle.

        Args:
            handle_id: The ROWID from the handle table
            include_reactions: If False, filter out tapbacks/reactions (default: False)
            limit: Maximum number of messages to return (default: None = all)

        Returns:
            List of message records with converted timestamps, sorted by date ascending.
            Each message includes:
                - ROWID: message ID
                - guid: globally unique message ID
                - text: message body (may be None)
                - handle_id: sender handle ID (0 if from you)
                - date: original Apple timestamp (nanoseconds)
                - date_unix: Unix timestamp (seconds)
                - date_datetime: Python datetime object
                - date_delivered, date_read: delivery/read timestamps
                - is_from_me: 1 if sent by you, 0 if received
                - cache_has_attachments: 1 if message has attachments
                - associated_message_guid: Non-null if this is a reaction
                - associated_message_type: Tapback type code
                - reply_to_guid: Thread reply reference
                - is_read: Read receipt status
                - service: "iMessage" or "SMS"
        """
        if not self.connection:
            raise iMessageDatabaseError("No active database connection")

        # Build query with optional reaction filter
        # Query logic:
        # 1. Find all 1-on-1 chats (exactly 2 participants) that include this handle
        # 2. Get all messages from those chats
        # This filters out group chats automatically
        query = """
            SELECT DISTINCT
                m.ROWID,
                m.guid,
                m.text,
                m.handle_id,
                m.date,
                m.date_delivered,
                m.date_read,
                m.is_from_me,
                m.cache_has_attachments,
                m.associated_message_guid,
                m.associated_message_type,
                m.reply_to_guid,
                m.is_read,
                m.service
            FROM message m
            INNER JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            INNER JOIN chat_handle_join chj ON cmj.chat_id = chj.chat_id
            WHERE chj.handle_id = ?
              AND cmj.chat_id IN (
                  -- Only include chats with 1-2 participants (1-on-1)
                  -- 1 participant = self-chat or missing join entry
                  -- 2 participants = standard 1-on-1
                  SELECT chat_id
                  FROM chat_handle_join
                  GROUP BY chat_id
                  HAVING COUNT(DISTINCT handle_id) <= 2
              )
        """

        if not include_reactions:
            query += " AND (associated_message_type = 0 OR associated_message_type IS NULL)"

        query += " ORDER BY date ASC"

        if limit:
            query += f" LIMIT {limit}"

        cursor = self.connection.cursor()
        cursor.execute(query, (handle_id,))

        messages = []
        for row in cursor.fetchall():
            msg = dict(row)

            # Convert Apple timestamps to Unix and datetime
            msg["date_unix"] = TimestampConverter.apple_to_unix(msg["date"])
            msg["date_datetime"] = TimestampConverter.apple_to_datetime(msg["date"])
            msg["date_delivered_unix"] = TimestampConverter.apple_to_unix(msg["date_delivered"])
            msg["date_read_unix"] = TimestampConverter.apple_to_unix(msg["date_read"])

            messages.append(msg)

        return messages

    def is_group_chat_handle(self, handle_id: int) -> bool:
        """Check if a handle is part of any group chats.

        Args:
            handle_id: The ROWID from the handle table

        Returns:
            True if handle participates in chats with 3+ participants
        """
        if not self.connection:
            raise iMessageDatabaseError("No active database connection")

        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT COUNT(DISTINCT chj2.handle_id) as participant_count
            FROM chat_handle_join chj1
            JOIN chat_handle_join chj2 ON chj1.chat_id = chj2.chat_id
            WHERE chj1.handle_id = ?
            GROUP BY chj1.chat_id
            HAVING COUNT(DISTINCT chj2.handle_id) >= 3
            LIMIT 1
            """,
            (handle_id,)
        )

        result = cursor.fetchone()
        return result is not None

    def get_chat_participants(self, chat_id: int) -> List[Dict[str, Any]]:
        """
        Get all participants (handles) in a specific chat.

        Args:
            chat_id: The ROWID from the chat table

        Returns:
            List of handle records participating in the chat
        """
        if not self.connection:
            raise iMessageDatabaseError("No active database connection")

        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT h.ROWID, h.id, h.country, h.service
            FROM handle h
            JOIN chat_handle_join chj ON h.ROWID = chj.handle_id
            WHERE chj.chat_id = ?
            ORDER BY h.ROWID
            """,
            (chat_id,)
        )

        return [dict(row) for row in cursor.fetchall()]

    def get_all_chats(self, include_group_chats: bool = True) -> List[Dict[str, Any]]:
        """
        Retrieve all chat conversations.

        Args:
            include_group_chats: If False, only return 1:1 chats (default: True)

        Returns:
            List of chat records with keys: ROWID, guid, chat_identifier,
            display_name, group_id, is_archived
        """
        if not self.connection:
            raise iMessageDatabaseError("No active database connection")

        query = """
            SELECT
                ROWID,
                guid,
                chat_identifier,
                display_name,
                group_id,
                is_archived
            FROM chat
        """

        if not include_group_chats:
            query += " WHERE display_name IS NULL AND group_id IS NULL"

        query += " ORDER BY ROWID"

        cursor = self.connection.cursor()
        cursor.execute(query)

        return [dict(row) for row in cursor.fetchall()]

    def get_message_attachments(self, message_id: int) -> List[Dict[str, Any]]:
        """
        Get all attachments for a specific message.

        Args:
            message_id: The ROWID from the message table

        Returns:
            List of attachment records with keys: ROWID, guid, filename,
            mime_type, total_bytes
        """
        if not self.connection:
            raise iMessageDatabaseError("No active database connection")

        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                a.ROWID,
                a.guid,
                a.filename,
                a.mime_type,
                a.total_bytes
            FROM attachment a
            JOIN message_attachment_join maj ON a.ROWID = maj.attachment_id
            WHERE maj.message_id = ?
            ORDER BY a.ROWID
            """,
            (message_id,)
        )

        return [dict(row) for row in cursor.fetchall()]

    def execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """
        Execute a custom read-only SQL query.

        WARNING: This method is provided for advanced use cases only.
        Use the provided methods when possible for safety and consistency.

        Args:
            query: SQL SELECT query (must be read-only)
            params: Query parameters for safe parameterization

        Returns:
            List of result rows as dictionaries

        Raises:
            iMessageDatabaseError: If attempting a non-SELECT query
        """
        if not self.connection:
            raise iMessageDatabaseError("No active database connection")

        # Basic safety check - only allow SELECT queries
        query_upper = query.strip().upper()
        if not query_upper.startswith("SELECT") and not query_upper.startswith("WITH"):
            raise iMessageDatabaseError(
                "Only SELECT queries are allowed. This is a read-only interface."
            )

        cursor = self.connection.cursor()
        cursor.execute(query, params)

        return [dict(row) for row in cursor.fetchall()]
