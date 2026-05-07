"""Statistical analysis functions for message conversations.

Implements all statistics defined in plan.md lines 133-288.
"""

from typing import List, Dict, Any, Optional, Tuple
import statistics
from collections import defaultdict


def compute_volume_stats(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute message and word volume statistics.

    Args:
        messages: List of message dicts with 'is_from_me' and 'word_count' keys

    Returns:
        Dictionary containing:
        - total_messages: total count of all messages
        - messages_from_me: count of messages from me
        - messages_from_them: count of messages from them
        - message_ratio: messages_from_me / total_messages
        - total_words_me: sum of word counts from me
        - total_words_them: sum of word counts from them
        - word_ratio: total_words_me / (total_words_me + total_words_them)
    """
    if not messages:
        return {
            'total_messages': 0,
            'messages_from_me': 0,
            'messages_from_them': 0,
            'message_ratio': None,
            'total_words_me': 0,
            'total_words_them': 0,
            'word_ratio': None,
        }

    total_messages = len(messages)
    messages_from_me = sum(1 for m in messages if m['is_from_me'] == 1)
    messages_from_them = total_messages - messages_from_me

    total_words_me = sum(m.get('word_count', 0) for m in messages if m['is_from_me'] == 1)
    total_words_them = sum(m.get('word_count', 0) for m in messages if m['is_from_me'] == 0)

    message_ratio = messages_from_me / total_messages if total_messages > 0 else None

    total_words = total_words_me + total_words_them
    word_ratio = total_words_me / total_words if total_words > 0 else None

    return {
        'total_messages': total_messages,
        'messages_from_me': messages_from_me,
        'messages_from_them': messages_from_them,
        'message_ratio': message_ratio,
        'total_words_me': total_words_me,
        'total_words_them': total_words_them,
        'word_ratio': word_ratio,
    }


def compute_response_times(session_messages: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """Calculate median response times within a session using turn-based burst algorithm.

    A turn ends when the other person starts speaking or the session ends.
    Response time = time between last message of person X's turn and first message
    of person Y's reply.

    Args:
        session_messages: List of messages in a session, sorted by date_unix ascending.
                         Must contain 'is_from_me' and 'date_unix' keys.

    Returns:
        Dictionary containing:
        - median_my_rt: median of my response times in seconds (or None)
        - median_their_rt: median of their response times in seconds (or None)
    """
    my_rts = []
    their_rts = []

    i = 0
    while i < len(session_messages):
        # Find end of current speaker's burst
        current_speaker = session_messages[i]['is_from_me']
        burst_end_time = session_messages[i]['date_unix']

        j = i
        while j < len(session_messages) and session_messages[j]['is_from_me'] == current_speaker:
            burst_end_time = session_messages[j]['date_unix']
            j += 1

        # If there's a response, calculate response time
        if j < len(session_messages):
            response_time = session_messages[j]['date_unix'] - burst_end_time

            if current_speaker == 1:  # I spoke, they responded
                their_rts.append(response_time)
            else:  # They spoke, I responded
                my_rts.append(response_time)

        i = j

    median_my_rt = statistics.median(my_rts) if my_rts else None
    median_their_rt = statistics.median(their_rts) if their_rts else None

    return {
        'median_my_rt': median_my_rt,
        'median_their_rt': median_their_rt,
    }


def compute_initiator_ratio(sessions: Dict[int, List[Dict[str, Any]]]) -> Optional[float]:
    """Calculate what fraction of sessions were initiated by them.

    Initiator is whoever sends the first message in a session.
    Co-initiated sessions (both parties message within 3 minutes) are excluded.

    Args:
        sessions: Dictionary mapping session_id to list of messages

    Returns:
        Ratio of sessions initiated by them (0.0 to 1.0), or None if no valid sessions
    """
    if not sessions:
        return None

    CO_INITIATION_WINDOW = 180  # 3 minutes in seconds

    initiated_by_them = 0
    valid_sessions = 0

    for session_messages in sessions.values():
        if not session_messages:
            continue

        first_msg = session_messages[0]

        # Check for co-initiation
        is_co_initiated = False
        for msg in session_messages[1:]:
            time_gap = msg['date_unix'] - first_msg['date_unix']
            if time_gap > CO_INITIATION_WINDOW:
                break
            # If other person messages within 3 minutes, it's co-initiated
            if msg['is_from_me'] != first_msg['is_from_me']:
                is_co_initiated = True
                break

        if not is_co_initiated:
            valid_sessions += 1
            if first_msg['is_from_me'] == 0:
                initiated_by_them += 1

    if valid_sessions == 0:
        return None

    return initiated_by_them / valid_sessions


def compute_reciprocity(messages: List[Dict[str, Any]]) -> Optional[float]:
    """Calculate reciprocity score based on word balance.

    Reciprocity = min(words_me, words_them) / max(words_me, words_them)
    Range 0-1. Score of 1.0 = perfectly balanced, 0.3 = one person writes 3x more.

    Args:
        messages: List of message dicts with 'is_from_me' and 'word_count' keys

    Returns:
        Reciprocity score (0.0 to 1.0), or None if not computable
    """
    if not messages:
        return None

    words_me = sum(m.get('word_count', 0) for m in messages if m['is_from_me'] == 1)
    words_them = sum(m.get('word_count', 0) for m in messages if m['is_from_me'] == 0)

    if words_me == 0 and words_them == 0:
        return None

    max_words = max(words_me, words_them)
    if max_words == 0:
        return None

    min_words = min(words_me, words_them)

    return min_words / max_words


def compute_ghost_rate(sessions: Dict[int, List[Dict[str, Any]]], direction: str = 'me') -> Optional[float]:
    """Calculate percentage of unanswered message bursts within 48 hours.

    Ghost rate = percentage of your message bursts (at end of your turn, ending a session)
    that received no reply within 48 hours.

    Args:
        sessions: Dictionary mapping session_id to list of messages, sorted by session_id
        direction: 'me' = sessions where I had last word with no reply,
                  'them' = sessions where they had last word with no reply

    Returns:
        Ghost rate as a fraction (0.0 to 1.0), or None if not computable
    """
    if not sessions:
        return None

    GHOST_THRESHOLD = 48 * 3600  # 48 hours in seconds

    ghosted = 0
    total = 0

    # Sort sessions by session_id to get chronological order
    sorted_session_ids = sorted(sessions.keys())

    for i, session_id in enumerate(sorted_session_ids):
        session_messages = sessions[session_id]
        if not session_messages:
            continue

        last_msg = session_messages[-1]

        # Check if this session ended with a message from the direction we're checking
        if direction == 'me':
            if last_msg['is_from_me'] != 1:
                continue
        else:  # direction == 'them'
            if last_msg['is_from_me'] != 0:
                continue

        total += 1

        # Check if there's a next session and calculate time to reply
        if i + 1 < len(sorted_session_ids):
            next_session_id = sorted_session_ids[i + 1]
            next_session_messages = sessions[next_session_id]
            if next_session_messages:
                next_session_start = next_session_messages[0]
                time_to_reply = next_session_start['date_unix'] - last_msg['date_unix']
                if time_to_reply > GHOST_THRESHOLD:
                    ghosted += 1
            else:
                ghosted += 1
        else:
            # No next session = ghosted
            ghosted += 1

    if total == 0:
        return None

    return ghosted / total


def compute_conversation_depth(sessions: Dict[int, List[Dict[str, Any]]]) -> Dict[str, Optional[float]]:
    """Calculate conversation depth metrics.

    Args:
        sessions: Dictionary mapping session_id to list of messages

    Returns:
        Dictionary containing:
        - avg_messages_per_session: mean number of messages per session
        - avg_words_per_session: mean word count per session
        - depth_variance: standard deviation of messages-per-session
    """
    if not sessions:
        return {
            'avg_messages_per_session': None,
            'avg_words_per_session': None,
            'depth_variance': None,
        }

    messages_per_session = []
    words_per_session = []

    for session_messages in sessions.values():
        if not session_messages:
            continue

        messages_per_session.append(len(session_messages))

        total_words = sum(m.get('word_count', 0) for m in session_messages)
        words_per_session.append(total_words)

    if not messages_per_session:
        return {
            'avg_messages_per_session': None,
            'avg_words_per_session': None,
            'depth_variance': None,
        }

    avg_messages = statistics.mean(messages_per_session)
    avg_words = statistics.mean(words_per_session)

    # Calculate variance (std dev) of messages per session
    if len(messages_per_session) > 1:
        depth_variance = statistics.stdev(messages_per_session)
    else:
        depth_variance = 0.0

    return {
        'avg_messages_per_session': avg_messages,
        'avg_words_per_session': avg_words,
        'depth_variance': depth_variance,
    }


def compute_message_length_stats(messages: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """Calculate median message length per direction.

    Filters out tapbacks and empty messages (word_count = 0).

    Args:
        messages: List of message dicts with 'is_from_me' and 'word_count' keys

    Returns:
        Dictionary containing:
        - median_length_me: median word count of my messages
        - median_length_them: median word count of their messages
    """
    if not messages:
        return {
            'median_length_me': None,
            'median_length_them': None,
        }

    # Filter out empty messages and tapbacks (word_count = 0)
    lengths_me = [m.get('word_count', 0) for m in messages
                  if m['is_from_me'] == 1 and m.get('word_count', 0) > 0]
    lengths_them = [m.get('word_count', 0) for m in messages
                    if m['is_from_me'] == 0 and m.get('word_count', 0) > 0]

    median_length_me = statistics.median(lengths_me) if lengths_me else None
    median_length_them = statistics.median(lengths_them) if lengths_them else None

    return {
        'median_length_me': median_length_me,
        'median_length_them': median_length_them,
    }


def compute_streaks(sessions: Dict[int, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Calculate streak and cadence statistics.

    Streak = consecutive calendar days with at least one session.
    Cadence = median days between session starts, trailing 90 days.

    Args:
        sessions: Dictionary mapping session_id to list of messages

    Returns:
        Dictionary containing:
        - longest_streak: longest consecutive days with sessions
        - current_streak: current consecutive days with sessions (from most recent)
        - cadence: median days between session starts (trailing 90 days)
    """
    if not sessions:
        return {
            'longest_streak': 0,
            'current_streak': 0,
            'cadence': None,
        }

    # Get start date (calendar day) for each session
    session_dates = []
    for session_messages in sessions.values():
        if session_messages:
            # Convert unix timestamp to calendar day (days since epoch)
            start_unix = session_messages[0]['date_unix']
            calendar_day = start_unix // 86400  # 86400 seconds per day
            session_dates.append(calendar_day)

    if not session_dates:
        return {
            'longest_streak': 0,
            'current_streak': 0,
            'cadence': None,
        }

    # Sort and get unique days
    unique_days = sorted(set(session_dates))

    # Calculate longest and current streak
    longest_streak = 1
    current_streak_val = 1
    temp_streak = 1

    for i in range(1, len(unique_days)):
        if unique_days[i] == unique_days[i - 1] + 1:
            temp_streak += 1
        else:
            longest_streak = max(longest_streak, temp_streak)
            temp_streak = 1

    longest_streak = max(longest_streak, temp_streak)

    # Calculate current streak (from most recent day backwards)
    # Only count as "current" if last session was within 3 days
    import time
    today = int(time.time()) // 86400
    days_since_last = today - unique_days[-1]

    if days_since_last > 3:
        # Streak is broken (no activity in 3+ days)
        current_streak_val = 0
    else:
        current_streak_val = 1
        for i in range(len(unique_days) - 1, 0, -1):
            if unique_days[i] == unique_days[i - 1] + 1:
                current_streak_val += 1
            else:
                break

    # Calculate cadence for trailing 90 days
    # Get sessions from last 90 days
    if session_dates:
        most_recent_day = max(session_dates)
        ninety_days_ago = most_recent_day - 90

        recent_session_dates = sorted([d for d in session_dates if d >= ninety_days_ago])

        if len(recent_session_dates) > 1:
            gaps = [recent_session_dates[i] - recent_session_dates[i - 1]
                   for i in range(1, len(recent_session_dates))]
            cadence = statistics.median(gaps) if gaps else None
        else:
            cadence = None
    else:
        cadence = None

    return {
        'longest_streak': longest_streak,
        'current_streak': current_streak_val,
        'cadence': cadence,
    }


def compute_all_stats(messages: List[Dict[str, Any]],
                     sessions: Optional[Dict[int, List[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    """Compute all statistics for a conversation.

    This is a convenience function that calls all individual stat functions
    and combines their results.

    Args:
        messages: List of message dicts with session_id assigned
        sessions: Optional pre-grouped sessions dict. If not provided, will be
                 computed from messages.

    Returns:
        Dictionary containing all statistics combined
    """
    if not messages:
        return {
            'volume': compute_volume_stats([]),
            'response_times': {'median_my_rt': None, 'median_their_rt': None},
            'initiator_ratio': None,
            'reciprocity': None,
            'ghost_rate_me': None,
            'ghost_rate_them': None,
            'conversation_depth': compute_conversation_depth({}),
            'message_length': compute_message_length_stats([]),
            'streaks': compute_streaks({}),
        }

    # Group messages by session if not provided
    if sessions is None:
        sessions = {}
        for msg in messages:
            session_id = msg.get('session_id', 0)
            if session_id not in sessions:
                sessions[session_id] = []
            sessions[session_id].append(msg)

    # Compute all stats
    volume = compute_volume_stats(messages)

    # For response times, aggregate across all sessions
    all_my_rts = []
    all_their_rts = []
    for session_messages in sessions.values():
        rt_stats = compute_response_times(session_messages)
        # Get the raw response times from the session
        i = 0
        while i < len(session_messages):
            current_speaker = session_messages[i]['is_from_me']
            burst_end_time = session_messages[i]['date_unix']
            j = i
            while j < len(session_messages) and session_messages[j]['is_from_me'] == current_speaker:
                burst_end_time = session_messages[j]['date_unix']
                j += 1
            if j < len(session_messages):
                response_time = session_messages[j]['date_unix'] - burst_end_time
                if current_speaker == 1:
                    all_their_rts.append(response_time)
                else:
                    all_my_rts.append(response_time)
            i = j

    response_times = {
        'median_my_rt': statistics.median(all_my_rts) if all_my_rts else None,
        'median_their_rt': statistics.median(all_their_rts) if all_their_rts else None,
    }

    initiator_ratio = compute_initiator_ratio(sessions)
    reciprocity = compute_reciprocity(messages)
    ghost_rate_me = compute_ghost_rate(sessions, direction='me')
    ghost_rate_them = compute_ghost_rate(sessions, direction='them')
    conversation_depth = compute_conversation_depth(sessions)
    message_length = compute_message_length_stats(messages)
    streaks = compute_streaks(sessions)

    return {
        'volume': volume,
        'response_times': response_times,
        'initiator_ratio': initiator_ratio,
        'reciprocity': reciprocity,
        'ghost_rate_me': ghost_rate_me,
        'ghost_rate_them': ghost_rate_them,
        'conversation_depth': conversation_depth,
        'message_length': message_length,
        'streaks': streaks,
    }
