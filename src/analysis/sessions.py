"""Session segmentation for message conversations.

A session is a continuous exchange where no gap between consecutive messages exceeds 4 hours.
"""

from typing import List, Dict, Any

# Session gap threshold: 4 hours in seconds
SESSION_GAP_SECONDS = 4 * 60 * 60  # 14400 seconds


def assign_sessions(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Assign session IDs to a list of messages based on time gaps.

    A new session begins when the gap between consecutive messages exceeds
    SESSION_GAP_SECONDS (4 hours). Messages must be sorted by date in
    ascending order.

    Args:
        messages: List of message dicts sorted by date ascending.
                 Each message must have a 'date_unix' field containing
                 a Unix timestamp (seconds since 1970-01-01).

    Returns:
        Same list of messages with 'session_id' field added to each message.
        Session IDs start at 0 and increment for each new session.

    Edge cases:
        - Empty list: returns empty list
        - Single message: assigned session_id = 0
        - Gap exactly 4h (14400s): same session (gap not > threshold)
        - Gap 4h + 1s (14401s): new session (gap > threshold)

    Example:
        >>> messages = [
        ...     {'date_unix': 1000, 'text': 'hi'},
        ...     {'date_unix': 2000, 'text': 'hello'},
        ...     {'date_unix': 20000, 'text': 'hey again'}  # > 4h gap
        ... ]
        >>> result = assign_sessions(messages)
        >>> [m['session_id'] for m in result]
        [0, 0, 1]
    """
    if not messages:
        return messages

    session_id = 0

    for i, msg in enumerate(messages):
        if i == 0:
            msg['session_id'] = session_id
            continue

        gap = msg['date_unix'] - messages[i - 1]['date_unix']
        if gap > SESSION_GAP_SECONDS:
            session_id += 1

        msg['session_id'] = session_id

    return messages


def group_by_session(messages: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    """Group messages into sessions.

    Args:
        messages: List of messages with session_id assigned

    Returns:
        Dictionary mapping session_id to list of messages
    """
    sessions = {}
    for msg in messages:
        session_id = msg.get('session_id', 0)
        if session_id not in sessions:
            sessions[session_id] = []
        sessions[session_id].append(msg)

    return sessions


def get_session_stats(session_messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate basic statistics for a session.

    Args:
        session_messages: List of messages in a session, sorted by date

    Returns:
        Dictionary with session statistics
    """
    if not session_messages:
        return {
            'message_count': 0,
            'duration_seconds': 0,
            'initiator_is_me': None,
            'messages_from_me': 0,
            'messages_from_them': 0,
            'words_from_me': 0,
            'words_from_them': 0,
            'start_time': None,
            'end_time': None,
        }

    first_msg = session_messages[0]
    last_msg = session_messages[-1]

    messages_from_me = sum(1 for m in session_messages if m['is_from_me'] == 1)
    messages_from_them = len(session_messages) - messages_from_me

    words_from_me = sum(m.get('word_count', 0) for m in session_messages if m['is_from_me'] == 1)
    words_from_them = sum(m.get('word_count', 0) for m in session_messages if m['is_from_me'] == 0)

    return {
        'message_count': len(session_messages),
        'duration_seconds': last_msg['date_unix'] - first_msg['date_unix'],
        'initiator_is_me': first_msg['is_from_me'] == 1,
        'messages_from_me': messages_from_me,
        'messages_from_them': messages_from_them,
        'words_from_me': words_from_me,
        'words_from_them': words_from_them,
        'start_time': first_msg['date_unix'],
        'end_time': last_msg['date_unix'],
        'start_datetime': first_msg.get('date_datetime'),
        'end_datetime': last_msg.get('date_datetime'),
    }


def get_initiator_ratio(sessions: Dict[int, List[Dict[str, Any]]]) -> float:
    """Calculate what fraction of sessions were initiated by them.

    Args:
        sessions: Dictionary of session_id to message list

    Returns:
        Ratio of sessions initiated by them (0.0 to 1.0), or None if no sessions
    """
    if not sessions:
        return None

    # Exclude co-initiated sessions (both parties message within 3 minutes)
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


def compute_response_times(session_messages: List[Dict[str, Any]]) -> tuple:
    """Calculate response times within a session.

    Response time = time between the last message of person X's turn
    and the first message of person Y's reply.

    Args:
        session_messages: List of messages in a session, sorted by date

    Returns:
        Tuple of (my_response_times, their_response_times) in seconds
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

    return my_rts, their_rts


def get_all_response_times(sessions: Dict[int, List[Dict[str, Any]]]) -> tuple:
    """Calculate response times across all sessions.

    Args:
        sessions: Dictionary of session_id to message list

    Returns:
        Tuple of (all_my_response_times, all_their_response_times) in seconds
    """
    all_my_rts = []
    all_their_rts = []

    for session_messages in sessions.values():
        my_rts, their_rts = compute_response_times(session_messages)
        all_my_rts.extend(my_rts)
        all_their_rts.extend(their_rts)

    return all_my_rts, all_their_rts
