"""Additional filters for contact classification.

Implements 6 additional filters beyond spam detection:
1. filter_transient: Excludes one-time exchanges (<=10 messages, <=3 days, <=2 sessions)
2. filter_dormant: Archives contacts with no message in >730 days
3. filter_group_chat: Defers group chats to separate view
4. filter_tapback_only: Excludes contacts with >=80% tapbacks and <=5 real messages
5. filter_automated_regular: Excludes automated services with regular patterns
6. tag_sms_quality: Tags SMS contacts for data quality awareness

Each filter returns: (action, reason_dict) where action is 'exclude', 'tag', 'defer', or 'pass'.
"""

from typing import List, Dict, Any, Tuple
from datetime import datetime, timedelta
from src.utils.config import get_config


class TransientContactFilter:
    """Filter for one-time or very brief exchanges.

    Catches: Uber drivers, Airbnb hosts, one-time contractors.
    Mode: exclude
    """

    def __init__(self):
        """Initialize transient filter with configuration."""
        self.config = get_config()
        self.thresholds = self.config.get('transient_thresholds')

    def filter_transient(self, messages: List[Dict[str, Any]], sessions: Dict[int, List]) -> Tuple[str, Dict[str, Any]]:
        """Check if contact is transient.

        All three conditions must be true:
        - Total messages <= 10
        - Time span <= 3 days
        - Sessions <= 2

        Args:
            messages: All messages for contact
            sessions: Session dictionary

        Returns:
            Tuple of (action, reason_dict) where action is 'exclude' or 'pass'
        """
        reason = {
            'message_count': len(messages),
            'session_count': len(sessions),
            'time_span_days': 0.0,
        }

        # Check message count
        if len(messages) > self.thresholds['max_messages']:
            return ('pass', reason)

        # Check session count
        if len(sessions) > self.thresholds['max_sessions']:
            return ('pass', reason)

        # Check time span
        if messages:
            first_msg = min(messages, key=lambda m: m['date_unix'])
            last_msg = max(messages, key=lambda m: m['date_unix'])
            time_span_days = (last_msg['date_unix'] - first_msg['date_unix']) / 86400
            reason['time_span_days'] = time_span_days

            if time_span_days > self.thresholds['max_time_span_days']:
                return ('pass', reason)

        # All three conditions met - this is transient
        reason['filter'] = 'transient'
        return ('exclude', reason)


class DormancyFilter:
    """Filter for dormant relationships.

    Identifies contacts not messaged in 2+ years.
    Mode: archive (exclude from active dashboard, keep in archived view)
    """

    def __init__(self):
        """Initialize dormancy filter with configuration."""
        self.config = get_config()
        self.threshold_days = self.config.dormancy_threshold_days

    def filter_dormant(
        self,
        messages: List[Dict[str, Any]],
        all_contacts_ranked: List[str] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Check if contact is dormant.

        Args:
            messages: All messages for contact
            all_contacts_ranked: Optional list of contact IDs ranked by total message volume

        Returns:
            Tuple of (action, reason_dict) where action is 'exclude' or 'pass'
        """
        reason = {
            'days_since_last': 0.0,
            'was_close_contact': False,
        }

        if not messages:
            reason['days_since_last'] = float('inf')
            reason['filter'] = 'dormant'
            return ('exclude', reason)

        last_msg = max(messages, key=lambda m: m['date_unix'])
        now = datetime.now().timestamp()
        days_since_last = (now - last_msg['date_unix']) / 86400
        reason['days_since_last'] = days_since_last

        # Check if dormant
        if days_since_last <= self.threshold_days:
            return ('pass', reason)

        # Contact is dormant - check if they were a close contact
        was_close = self._was_close_contact(messages, all_contacts_ranked)
        reason['was_close_contact'] = was_close
        reason['filter'] = 'dormant'

        # Return with appropriate tagging
        if was_close:
            reason['note'] = 'past_close_contact'

        return ('exclude', reason)

    def _was_close_contact(self, messages: List[Dict[str, Any]], all_contacts_ranked: List[str]) -> bool:
        """Check if this was a top 20 contact by volume.

        Args:
            messages: All messages for contact
            all_contacts_ranked: List of contact IDs ranked by total message volume

        Returns:
            True if this was a high-volume contact
        """
        if not messages or not all_contacts_ranked:
            return False

        contact_id = messages[0].get('contact_id')
        if not contact_id:
            return False

        return contact_id in all_contacts_ranked[:20]


class GroupChatFilter:
    """Filter for group conversations.

    Defers to separate view rather than excluding.
    Mode: defer to separate "Group Chats" view
    """

    def __init__(self, db_reader=None):
        """Initialize group chat filter.

        Args:
            db_reader: Optional MessageDBReader instance for checking group status
        """
        self.db_reader = db_reader

    def filter_group_chat(self, contact_id: str, messages: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
        """Check if contact represents a group chat.

        Detection: chat.display_name IS NOT NULL OR chat_id has >2 distinct handles.

        Args:
            contact_id: Contact identifier
            messages: All messages for contact

        Returns:
            Tuple of (action, reason_dict) where action is 'defer' or 'pass'
        """
        reason = {
            'contact_id': contact_id,
        }

        # Use database reader if available
        if self.db_reader:
            is_group = self.db_reader.is_group_chat(contact_id)
            reason['detection_method'] = 'database'
        else:
            # Fallback: check display_name in first message or identifier patterns
            is_group = False
            if messages and messages[0].get('display_name'):
                is_group = True
                reason['detection_method'] = 'display_name'
            elif 'chat' in contact_id.lower() or 'group' in contact_id.lower():
                is_group = True
                reason['detection_method'] = 'identifier_pattern'
            else:
                reason['detection_method'] = 'none'

        if is_group:
            reason['filter'] = 'group_chat'
            return ('defer', reason)

        return ('pass', reason)


class TapbackOnlyFilter:
    """Filter for contacts with almost exclusively reactions.

    Excludes contacts where 80%+ of messages are tapbacks and <=5 real messages.
    Mode: exclude
    """

    def __init__(self):
        """Initialize tapback-only filter with configuration."""
        self.config = get_config()
        self.thresholds = self.config.get('tapback_only_thresholds')

    def filter_tapback_only(
        self,
        all_messages: List[Dict[str, Any]],
        real_messages: List[Dict[str, Any]]
    ) -> Tuple[str, Dict[str, Any]]:
        """Check if contact is tapback-only.

        Criteria:
        - % of messages that are tapbacks (associated_message_type != 0) >= 80%
        - Total non-tapback messages <= 5

        Args:
            all_messages: All messages including tapbacks
            real_messages: Messages excluding tapbacks

        Returns:
            Tuple of (action, reason_dict) where action is 'exclude' or 'pass'
        """
        tapback_count = len(all_messages) - len(real_messages)
        tapback_percentage = tapback_count / len(all_messages) if all_messages else 0.0

        reason = {
            'total_messages': len(all_messages),
            'real_messages': len(real_messages),
            'tapback_count': tapback_count,
            'tapback_percentage': tapback_percentage,
        }

        if not all_messages:
            return ('pass', reason)

        # Check both conditions
        if (len(real_messages) <= self.thresholds['max_real_messages'] and
            tapback_percentage >= self.thresholds['min_tapback_percentage']):
            reason['filter'] = 'tapback_only'
            return ('exclude', reason)

        return ('pass', reason)


class AutomatedRegularFilter:
    """Filter for automated regular services.

    Detects services like calendar reminders, bank alerts with regular patterns.
    Different from spam - these may have replies from user.
    Mode: exclude
    """

    def __init__(self):
        """Initialize automated regular filter with configuration."""
        self.config = get_config()
        self.thresholds = self.config.get('automated_regular_thresholds')

    def filter_automated_regular(self, messages: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
        """Check if contact is automated regular service.

        Criteria (all must be true):
        - Send-time std dev < 1.5 hours across >= 20 messages
        - Message length std dev < 4 words
        - You-initiated ratio < 5%

        Args:
            messages: All messages for contact

        Returns:
            Tuple of (action, reason_dict) where action is 'exclude' or 'pass'
        """
        reason = {
            'message_count': len(messages),
        }

        if len(messages) < self.thresholds['min_messages_for_pattern']:
            return ('pass', reason)

        # Check send-time variance (messages from them)
        messages_from_them = [m for m in messages if m['is_from_me'] == 0]

        if not messages_from_them:
            return ('pass', reason)

        send_time_std = self._calculate_send_time_variance(messages_from_them)
        reason['send_time_std'] = send_time_std

        # Check message length variance
        length_std = self._calculate_length_variance(messages_from_them)
        reason['length_std'] = length_std

        # Check initiation ratio
        messages_from_me = sum(1 for m in messages if m['is_from_me'] == 1)
        initiated_ratio = messages_from_me / len(messages) if messages else 0
        reason['initiated_ratio'] = initiated_ratio

        # Flag if all conditions are met
        is_automated = (
            send_time_std < self.thresholds['max_send_time_std']
            and length_std < self.thresholds['max_length_std']
            and initiated_ratio < self.thresholds['max_initiated_ratio']
        )

        if is_automated:
            reason['filter'] = 'automated_regular'
            return ('exclude', reason)

        return ('pass', reason)

    def _calculate_send_time_variance(self, messages: List[Dict[str, Any]]) -> float:
        """Calculate standard deviation of send hour across messages.

        Args:
            messages: Messages from them

        Returns:
            Standard deviation of send hour in hours
        """
        if not messages:
            return 0.0

        hours = []
        for msg in messages:
            dt = msg.get('date_datetime')
            if dt:
                hours.append(dt.hour + dt.minute / 60.0)  # Include minutes for precision

        if not hours:
            return 0.0

        mean = sum(hours) / len(hours)
        variance = sum((h - mean) ** 2 for h in hours) / len(hours)
        return variance ** 0.5

    def _calculate_length_variance(self, messages: List[Dict[str, Any]]) -> float:
        """Calculate standard deviation of word count.

        Args:
            messages: Messages to analyze

        Returns:
            Standard deviation of word count
        """
        if not messages:
            return 0.0

        word_counts = [m.get('word_count', 0) for m in messages if m.get('text')]

        if not word_counts:
            return 0.0

        mean = sum(word_counts) / len(word_counts)
        variance = sum((wc - mean) ** 2 for wc in word_counts) / len(word_counts)
        return variance ** 0.5


class SMSQualityTag:
    """Tag for SMS messages (data quality indicator).

    Does not exclude - only tags for data quality awareness.
    Mode: tag only (never exclude)

    SMS messages are missing:
    - Reliable delivery timestamps (date_delivered = 0)
    - Read receipts (date_read = 0)
    - Precise send timestamps (carrier-delayed)
    """

    def tag_sms_quality(self, messages: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
        """Check if contact has SMS messages and calculate breakdown.

        Detection: message.service = 'SMS'

        Args:
            messages: All messages for contact

        Returns:
            Tuple of (action, reason_dict) where action is 'tag' or 'pass'
        """
        reason = {
            'has_sms': False,
            'sms_count': 0,
            'imessage_count': 0,
            'sms_percentage': 0.0,
        }

        if not messages:
            return ('pass', reason)

        sms_count = sum(1 for m in messages if m.get('service') == 'SMS')
        imessage_count = len(messages) - sms_count

        reason['has_sms'] = sms_count > 0
        reason['sms_count'] = sms_count
        reason['imessage_count'] = imessage_count
        reason['sms_percentage'] = sms_count / len(messages) if messages else 0.0
        reason['is_sms_only'] = sms_count == len(messages)
        reason['is_mixed'] = 0 < sms_count < len(messages)

        if sms_count > 0:
            reason['filter'] = 'sms_quality'
            reason['data_quality_warning'] = 'SMS messages lack reliable timestamps and read receipts'
            return ('tag', reason)

        return ('pass', reason)


class FilterPipeline:
    """Orchestrates all filters in sequence.

    Pipeline order:
    1. Spam / notification filter (exclude)
    2. Transient contact filter (exclude)
    3. Dormancy filter (archive)
    4. Group chat filter (defer)
    5. Tapback-only filter (exclude)
    6. Automated regular filter (exclude)
    7. SMS quality tag (tag only)

    Each filter returns: (action, reason_dict)
    - action: 'exclude', 'tag', 'defer', or 'pass'
    - reason_dict: contains filter-specific details
    """

    def __init__(self, spam_filter, db_reader=None, config=None):
        """Initialize filter pipeline.

        Args:
            spam_filter: SpamFilter instance
            db_reader: Optional MessageDBReader for group chat detection
            config: Optional config override for testing
        """
        self.spam_filter = spam_filter
        self.transient_filter = TransientContactFilter()
        self.dormancy_filter = DormancyFilter()
        self.group_chat_filter = GroupChatFilter(db_reader)
        self.tapback_only_filter = TapbackOnlyFilter()
        self.automated_regular_filter = AutomatedRegularFilter()
        self.sms_quality_tag = SMSQualityTag()
        self.config = config or get_config()

    def apply_filters(
        self,
        contact_id: str,
        messages: List[Dict[str, Any]],
        messages_with_tapbacks: List[Dict[str, Any]],
        sessions: Dict[int, List],
        all_contacts_ranked: List[str] = None,
    ) -> Dict[str, Any]:
        """Apply all filters to a contact in sequence.

        Args:
            contact_id: Contact identifier
            messages: Messages excluding tapbacks
            messages_with_tapbacks: All messages including tapbacks
            sessions: Session dictionary
            all_contacts_ranked: Optional ranked list of all contacts by volume

        Returns:
            Dictionary with filter results:
            {
                'contact_id': str,
                'final_action': 'include' | 'exclude' | 'defer',
                'tags': List[str],
                'filters': Dict[str, Tuple[str, Dict]],
                'reason': str (if excluded/deferred)
            }
        """
        result = {
            'contact_id': contact_id,
            'final_action': 'include',
            'tags': [],
            'filters': {},
        }

        # 1. Spam filter
        spam_result = self.spam_filter.detect(contact_id, messages)
        result['filters']['spam'] = spam_result
        if spam_result['is_spam']:
            result['final_action'] = 'exclude'
            result['reason'] = 'spam'
            return result
        if spam_result['classification'] == 'borderline':
            result['tags'].append('borderline_spam')

        # 2. Transient filter
        action, reason = self.transient_filter.filter_transient(messages, sessions)
        result['filters']['transient'] = (action, reason)
        if action == 'exclude':
            result['final_action'] = 'exclude'
            result['reason'] = 'transient'
            return result

        # 3. Dormancy filter
        action, reason = self.dormancy_filter.filter_dormant(messages, all_contacts_ranked)
        result['filters']['dormant'] = (action, reason)
        if action == 'exclude':
            result['final_action'] = 'exclude'
            result['reason'] = 'dormant'
            if reason.get('was_close_contact'):
                result['tags'].append('past_close_contact')
            return result

        # 4. Group chat filter
        action, reason = self.group_chat_filter.filter_group_chat(contact_id, messages)
        result['filters']['group_chat'] = (action, reason)
        if action == 'defer':
            result['final_action'] = 'defer'
            result['reason'] = 'group_chat'
            return result

        # 5. Tapback-only filter
        action, reason = self.tapback_only_filter.filter_tapback_only(
            messages_with_tapbacks, messages
        )
        result['filters']['tapback_only'] = (action, reason)
        if action == 'exclude':
            result['final_action'] = 'exclude'
            result['reason'] = 'tapback_only'
            return result

        # 6. Automated regular filter
        action, reason = self.automated_regular_filter.filter_automated_regular(messages)
        result['filters']['automated_regular'] = (action, reason)
        if action == 'exclude':
            result['final_action'] = 'exclude'
            result['reason'] = 'automated_regular'
            return result

        # 7. SMS quality tag (does not exclude)
        action, reason = self.sms_quality_tag.tag_sms_quality(messages)
        result['filters']['sms_quality'] = (action, reason)
        if action == 'tag':
            result['tags'].append('has_sms')
            if reason.get('is_sms_only'):
                result['tags'].append('sms_only')
            elif reason.get('is_mixed'):
                result['tags'].append('mixed_service')

        return result
