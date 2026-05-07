"""Spam and notification detection filter.

Detects automated messages, marketing, and service notifications
using pattern matching and behavioral signals.

Implements 6 detection signals with weighted scoring to classify contacts
as spam, borderline, or human based on message patterns and behavior.
"""

import re
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from src.utils.config import get_config


@dataclass
class SpamConfig:
    """Configuration for spam detection.

    Attributes:
        threshold: Minimum confidence score to classify as spam (default 0.7)
        weights: Dictionary of signal weights for scoring
        patterns: List of compiled regex patterns for keyword detection
        whitelist: List of contact IDs that are never filtered
        blacklist: List of contact IDs that are always filtered
    """

    threshold: float
    weights: Dict[str, float]
    patterns: List[re.Pattern]
    whitelist: List[str]
    blacklist: List[str]

    @classmethod
    def from_config(cls) -> 'SpamConfig':
        """Create SpamConfig from global configuration.

        Returns:
            SpamConfig instance loaded from config
        """
        config = get_config()

        return cls(
            threshold=config.get('spam_threshold', 0.7),
            weights=config.get('spam_weights', {}),
            patterns=[
                re.compile(p, re.IGNORECASE)
                for p in config.get('spam_patterns', [])
            ],
            whitelist=config.get('whitelist', []),
            blacklist=config.get('blacklist', [])
        )


class SpamDetector:
    """Spam and notification detection for contacts.

    Uses 6 behavioral signals to compute a spam confidence score:
    1. Zero replies ever: ≥20 messages from them, 0 from you
    2. Zero reply streaks: ≥10 consecutive messages without reply
    3. High message velocity: ≥5 messages in 10 minutes
    4. Length uniformity: ≥80% under 12 words AND stddev < 3
    5. Keyword patterns: Matches notification regex patterns
    6. Alphanumeric sender: Short code format (not phone/email)

    Scoring:
    - Each signal contributes its weight to the total score
    - Score ranges from 0.0 to 1.0
    - ≥0.7: spam (excluded from all stats)
    - 0.4-0.7: borderline (flagged, shown separately)
    - <0.4: human contact (included normally)

    Whitelist/blacklist overrides apply before signal detection.
    """

    def __init__(self, config: SpamConfig = None):
        """Initialize spam detector.

        Args:
            config: Optional SpamConfig. If None, loads from global config.
        """
        self.config = config or SpamConfig.from_config()

    def detect(self, contact_id: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect spam status for a contact.

        Args:
            contact_id: Contact identifier (phone number, email, or service ID)
            messages: List of all messages for this contact

        Returns:
            Dictionary containing:
                - contact_id: str
                - classification: 'spam' | 'borderline' | 'human'
                - confidence: float (0.0-1.0)
                - is_spam: bool (True if confidence >= threshold)
                - signals: dict of detected signals
        """
        # Check whitelist/blacklist first
        if contact_id in self.config.whitelist:
            return {
                'contact_id': contact_id,
                'classification': 'human',
                'confidence': 0.0,
                'is_spam': False,
                'signals': {'whitelisted': True}
            }

        if contact_id in self.config.blacklist:
            return {
                'contact_id': contact_id,
                'classification': 'spam',
                'confidence': 1.0,
                'is_spam': True,
                'signals': {'blacklisted': True}
            }

        # Calculate spam score using detection signals
        confidence, signals = self.calculate_score(contact_id, messages)

        # Classify based on confidence thresholds
        if confidence >= self.config.threshold:
            classification = 'spam'
        elif confidence >= 0.4:
            classification = 'borderline'
        else:
            classification = 'human'

        return {
            'contact_id': contact_id,
            'classification': classification,
            'confidence': confidence,
            'is_spam': confidence >= self.config.threshold,
            'signals': signals
        }

    def calculate_score(self, contact_id: str, messages: List[Dict[str, Any]]) -> Tuple[float, Dict[str, Any]]:
        """Calculate spam confidence score for a contact.

        Evaluates all 6 detection signals and computes a weighted score.

        Args:
            contact_id: Contact identifier
            messages: List of all messages for this contact

        Returns:
            Tuple of (confidence: float, signals: dict)
            - confidence: Score from 0.0 to 1.0
            - signals: Dictionary of detected signals with details
        """
        if not messages:
            return 0.0, {}

        signals = {}
        score = 0.0

        # Signal 1: Zero replies ever (≥20 from them, 0 from you)
        if self._check_zero_reply_ever(messages):
            signals['zero_reply_ever'] = True
            score += self.config.weights.get('zero_reply_ever', 0.6)

        # Signal 2: Zero reply streaks (≥10 consecutive)
        max_streak = self._check_zero_reply_streak(messages)
        if max_streak >= 10:
            signals['zero_reply_streak'] = max_streak
            score += self.config.weights.get('zero_reply_streak', 0.4)

        # Signal 3: High message velocity (≥5 in 10 minutes)
        if self._check_high_velocity(messages):
            signals['high_velocity'] = True
            score += self.config.weights.get('high_velocity', 0.3)

        # Signal 4: Length uniformity (≥80% under 12 words, stddev < 3)
        if self._check_length_uniformity(messages):
            signals['length_uniformity'] = True
            score += self.config.weights.get('length_uniformity', 0.3)

        # Signal 5: Keyword pattern matches
        keyword_matches = self._check_keyword_match(messages)
        if keyword_matches:
            signals['keyword_matches'] = keyword_matches
            # Weight is capped at the configured value
            score += min(
                len(keyword_matches) * 0.1,
                self.config.weights.get('keyword_match', 0.4)
            )

        # Signal 6: Alphanumeric sender ID (short code, not phone/email)
        if self._check_alphanumeric_sender(contact_id):
            signals['alphanumeric_sender'] = True
            score += self.config.weights.get('alphanumeric_sender', 0.5)

        # Cap final score at 1.0
        score = min(score, 1.0)

        return score, signals

    def _check_zero_reply_ever(self, messages: List[Dict[str, Any]]) -> bool:
        """Check for one-sided volume: ≥20 from them, 0 from you.

        Args:
            messages: List of messages

        Returns:
            True if threshold met (strong spam signal)
        """
        messages_from_me = sum(1 for m in messages if m.get('is_from_me') == 1)
        messages_from_them = sum(1 for m in messages if m.get('is_from_me') == 0)

        return messages_from_them >= 20 and messages_from_me == 0

    def _check_zero_reply_streak(self, messages: List[Dict[str, Any]]) -> int:
        """Calculate longest streak of consecutive messages from them.

        Resets streak if gap between messages > 24 hours (not spam, just slow replies).

        Args:
            messages: List of messages (should be sorted by date)

        Returns:
            Maximum consecutive message streak from them with no reply
        """
        max_streak = 0
        current_streak = 0
        last_msg_time = None
        TIME_GAP_THRESHOLD = 86400  # 24 hours in seconds

        for msg in messages:
            current_time = msg.get('date_unix')

            if msg.get('is_from_me') == 0:
                # Check if there's a large time gap (indicates slow reply, not spam)
                if last_msg_time and current_time and (current_time - last_msg_time) > TIME_GAP_THRESHOLD:
                    # Reset streak - this is not rapid-fire spam
                    current_streak = 1
                else:
                    current_streak += 1

                max_streak = max(max_streak, current_streak)
                last_msg_time = current_time
            else:
                current_streak = 0
                last_msg_time = current_time

        return max_streak

    def _check_high_velocity(self, messages: List[Dict[str, Any]]) -> bool:
        """Check for message bursts: ≥5 messages in 10 minutes.

        Args:
            messages: List of messages

        Returns:
            True if velocity pattern detected
        """
        VELOCITY_WINDOW = 600  # 10 minutes in seconds
        VELOCITY_THRESHOLD = 5

        # Filter to messages from them
        messages_from_them = [
            m for m in messages
            if m.get('is_from_me') == 0 and m.get('date_unix')
        ]

        # Check each message as potential burst start
        for i in range(len(messages_from_them)):
            count = 1
            start_time = messages_from_them[i]['date_unix']

            # Count messages within 10 minute window
            for j in range(i + 1, len(messages_from_them)):
                if messages_from_them[j]['date_unix'] - start_time <= VELOCITY_WINDOW:
                    count += 1
                else:
                    break

            if count >= VELOCITY_THRESHOLD:
                return True

        return False

    def _check_length_uniformity(self, messages: List[Dict[str, Any]]) -> bool:
        """Check for uniform short messages (templated content).

        Requirements:
        - ≥80% of messages under 12 words
        - Standard deviation of word count < 3

        Args:
            messages: List of messages

        Returns:
            True if uniformity pattern detected
        """
        # Need at least 5 messages to detect pattern
        if len(messages) < 5:
            return False

        # Extract word counts from text messages
        word_counts = []
        for msg in messages:
            if msg.get('text'):
                # Count words in message text
                text = msg['text'].strip()
                if text:
                    word_count = len(text.split())
                    word_counts.append(word_count)

        if not word_counts:
            return False

        # Check 1: ≥80% under 12 words
        short_messages = sum(1 for wc in word_counts if wc < 12)
        short_percentage = short_messages / len(word_counts)

        if short_percentage < 0.8:
            return False

        # Check 2: Standard deviation < 3
        mean = sum(word_counts) / len(word_counts)
        variance = sum((wc - mean) ** 2 for wc in word_counts) / len(word_counts)
        std_dev = variance ** 0.5

        return std_dev < 3.0

    def _check_keyword_match(self, messages: List[Dict[str, Any]]) -> List[str]:
        """Check for notification keyword patterns.

        Patterns include:
        - OTP codes (4-8 digits + "code", "pin", "otp", etc.)
        - Order tracking
        - Delivery status
        - Order updates
        - Marketing opt-out
        - Promotions
        - Appointments
        - Billing statements

        Args:
            messages: List of messages

        Returns:
            List of matched pattern descriptions
        """
        pattern_names = [
            'OTP code',
            'Order tracking',
            'Delivery status',
            'Order update',
            'Marketing opt-out',
            'Promotion',
            'Appointment',
            'Billing statement',
        ]

        matches = []

        for msg in messages:
            if not msg.get('text'):
                continue

            # Check each regex pattern
            for i, pattern in enumerate(self.config.patterns):
                if pattern.search(msg['text']):
                    pattern_name = pattern_names[i]
                    if pattern_name not in matches:
                        matches.append(pattern_name)

        return matches

    def _check_alphanumeric_sender(self, contact_id: str) -> bool:
        """Check if sender ID is a short alphanumeric code.

        Service IDs are typically short alphanumeric strings like:
        - "AMZN", "DoorDash", "Chase", "UPS"
        - Not phone numbers (digits with +/- or all digits)
        - Not email addresses (contains @)

        Args:
            contact_id: Contact identifier

        Returns:
            True if matches short alphanumeric sender format
        """
        if not contact_id:
            return False

        # Phone numbers contain + or are all digits (possibly with formatting)
        clean_for_phone = contact_id.replace('-', '').replace('(', '').replace(')', '').replace(' ', '')
        if '+' in contact_id or clean_for_phone.isdigit():
            return False

        # Email addresses contain @
        if '@' in contact_id:
            return False

        # Short alphanumeric strings (≤15 chars) are likely service IDs
        clean_id = contact_id.replace('-', '').replace('_', '').replace(' ', '')
        if len(clean_id) <= 15 and clean_id.isalnum():
            return True

        return False


# Backward compatibility alias
SpamFilter = SpamDetector
