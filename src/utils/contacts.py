"""Contact name resolution from JSON mapping file.

Uses pre-parsed vCard data from ~/.imessage-parser/contact_names.json
as a fallback when Contacts API access is unavailable.
"""

from typing import Optional, Dict
import re
import json
from pathlib import Path

try:
    from Contacts import CNContactStore, CNContactFormatter, CNContactFormatterStyle
    from Contacts import CNLabeledValue
    CONTACTS_AVAILABLE = True
except ImportError:
    CONTACTS_AVAILABLE = False


class ContactResolver:
    """Resolve phone numbers and emails to contact names from macOS Contacts."""

    def __init__(self):
        """Initialize contact resolver with access to macOS Contacts."""
        if not CONTACTS_AVAILABLE:
            raise ImportError("pyobjc-framework-Contacts not installed")

        self.store = CNContactStore()
        self._cache: Dict[str, Optional[str]] = {}

    def normalize_phone(self, phone: str) -> str:
        """Normalize phone number to digits only for comparison.

        Args:
            phone: Phone number in any format

        Returns:
            Digits-only string
        """
        return re.sub(r'\D', '', phone)

    def get_contact_name(self, identifier: str) -> Optional[str]:
        """Get contact name for phone number or email.

        Args:
            identifier: Phone number or email address

        Returns:
            Contact name if found, None otherwise
        """
        # Check cache first
        if identifier in self._cache:
            return self._cache[identifier]

        name = None

        # Determine if it's a phone or email
        if '@' in identifier:
            name = self._get_name_by_email(identifier)
        else:
            name = self._get_name_by_phone(identifier)

        # Cache result
        self._cache[identifier] = name
        return name

    def _get_name_by_phone(self, phone: str) -> Optional[str]:
        """Look up contact by phone number.

        Args:
            phone: Phone number

        Returns:
            Contact name if found
        """
        from Contacts import CNContactPhoneNumbersKey, CNContactType

        try:
            # Get all contacts with phone numbers
            keys = [CNContactPhoneNumbersKey, "givenName", "familyName", "organizationName"]
            contacts = self.store.unifiedContactsMatchingPredicate_keysToFetch_error_(
                None, keys, None
            )[0]

            normalized_input = self.normalize_phone(phone)

            for contact in contacts:
                phone_numbers = contact.phoneNumbers()
                if phone_numbers:
                    for phone_number in phone_numbers:
                        contact_phone = phone_number.value().stringValue()
                        normalized_contact = self.normalize_phone(contact_phone)

                        # Match if normalized numbers end the same way (handles country codes)
                        if (normalized_input.endswith(normalized_contact[-10:]) or
                            normalized_contact.endswith(normalized_input[-10:])):
                            return self._format_contact_name(contact)

            return None

        except Exception as e:
            print(f"Error looking up phone {phone}: {e}")
            return None

    def _get_name_by_email(self, email: str) -> Optional[str]:
        """Look up contact by email address.

        Args:
            email: Email address

        Returns:
            Contact name if found
        """
        from Contacts import CNContactEmailAddressesKey

        try:
            # Get all contacts with email addresses
            keys = [CNContactEmailAddressesKey, "givenName", "familyName", "organizationName"]
            contacts = self.store.unifiedContactsMatchingPredicate_keysToFetch_error_(
                None, keys, None
            )[0]

            email_lower = email.lower()

            for contact in contacts:
                email_addresses = contact.emailAddresses()
                if email_addresses:
                    for email_addr in email_addresses:
                        contact_email = str(email_addr.value()).lower()
                        if contact_email == email_lower:
                            return self._format_contact_name(contact)

            return None

        except Exception as e:
            print(f"Error looking up email {email}: {e}")
            return None

    def _format_contact_name(self, contact) -> str:
        """Format contact name from CNContact object.

        Args:
            contact: CNContact object

        Returns:
            Formatted name string
        """
        # Try using the formatter first (handles all name components properly)
        formatter = CNContactFormatter.alloc().init()
        formatted = formatter.stringFromContact_(contact)

        if formatted:
            return formatted

        # Fallback: build name manually
        given = contact.givenName() or ""
        family = contact.familyName() or ""
        org = contact.organizationName() or ""

        if given or family:
            return f"{given} {family}".strip()
        elif org:
            return org
        else:
            return "Unknown"


def load_contact_map() -> Dict[str, str]:
    """Load contact mappings from JSON file.

    Returns:
        Dictionary mapping phone/email to name
    """
    json_path = Path.home() / ".imessage-parser" / "contact_names.json"

    if not json_path.exists():
        return {}

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


# Cache the contact map globally
_CONTACT_MAP = None


def get_contact_name(identifier: str) -> Optional[str]:
    """Get contact name for phone number or email.

    Tries JSON file first (fast), falls back to Contacts API if available.

    Args:
        identifier: Phone number or email

    Returns:
        Contact name if found, None otherwise
    """
    global _CONTACT_MAP

    # Load JSON map once
    if _CONTACT_MAP is None:
        _CONTACT_MAP = load_contact_map()

    # Try JSON lookup first (most common case)
    if identifier in _CONTACT_MAP:
        return _CONTACT_MAP[identifier]

    # Try normalized phone lookup for JSON
    if '@' not in identifier:
        # Normalize phone and try again
        normalized = re.sub(r'[^\d+]', '', identifier)
        if not normalized.startswith('+') and len(normalized) == 10:
            normalized = f"+1{normalized}"
        elif not normalized.startswith('+') and len(normalized) == 11 and normalized.startswith('1'):
            normalized = f"+{normalized}"

        if normalized in _CONTACT_MAP:
            return _CONTACT_MAP[normalized]

    # Fallback to Contacts API if available
    if CONTACTS_AVAILABLE:
        try:
            resolver = ContactResolver()
            return resolver.get_contact_name(identifier)
        except Exception:
            pass

    return None
