#!/usr/bin/env python3
"""Generate a full JSON report of top contacts for web display."""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.db.reader import iMessageDatabaseReader
from src.utils.config import get_config
from src.utils.contacts import get_contact_name
from src.filters.spam import SpamDetector
from src.filters.additional import FilterPipeline
from src.analysis.sessions import assign_sessions
from src.analysis.stats import compute_all_stats


def analyze_contact_for_report(db, handle_id, handle_identifier):
    """Analyze a contact and return structured data."""

    contact_name = get_contact_name(handle_identifier)

    # Load messages
    messages = db.get_messages_for_handle(handle_id)

    if not messages:
        return None

    # Auto-whitelist if contact has a name
    if contact_name:
        spam_result = {
            'classification': 'human',
            'confidence': 0.0,
            'is_spam': False
        }
    else:
        spam_detector = SpamDetector()
        spam_result = spam_detector.detect(handle_identifier, messages)

    if spam_result['classification'] == 'spam':
        return None

    # Skip filter pipeline spam check (already done)
    class PassthroughSpamDetector:
        def detect(self, contact_id, messages):
            return {'is_spam': False, 'classification': 'human', 'confidence': 0.0}

    filter_pipeline = FilterPipeline(PassthroughSpamDetector(), None)
    messages_with_sessions_temp = assign_sessions(messages)
    sessions_dict = {}
    for msg in messages_with_sessions_temp:
        sid = msg['session_id']
        if sid not in sessions_dict:
            sessions_dict[sid] = []
        sessions_dict[sid].append(msg)

    filter_result = filter_pipeline.apply_filters(
        handle_identifier,
        messages,
        messages,
        sessions_dict
    )

    if filter_result['final_action'] in ['exclude', 'defer']:
        return None

    # Compute stats
    messages_with_sessions = assign_sessions(messages)
    num_sessions = len(set(msg['session_id'] for msg in messages_with_sessions))
    stats = compute_all_stats(messages_with_sessions)

    # Build report entry
    return {
        'name': contact_name or handle_identifier,
        'identifier': handle_identifier,
        'total_messages': len(messages),
        'sessions': num_sessions,
        'message_ratio': stats['volume']['message_ratio'],
        'word_ratio': stats['volume'].get('word_ratio'),
        'my_median_response_time': stats['response_times'].get('median_my_rt') if stats.get('response_times') else None,
        'their_median_response_time': stats['response_times'].get('median_their_rt') if stats.get('response_times') else None,
        'initiator_ratio': stats.get('initiator_ratio'),
        'reciprocity': stats.get('reciprocity'),
        'ghost_rate': stats.get('ghost_rate'),
        'avg_messages_per_session': stats['conversation_depth'].get('avg_messages_per_session') if stats.get('conversation_depth') else None,
        'longest_streak': stats['streaks'].get('longest_streak', 0) if stats.get('streaks') else 0,
        'current_streak': stats['streaks'].get('current_streak', 0) if stats.get('streaks') else 0,
    }


def main():
    """Generate report for top 25 contacts."""

    print("Generating Top 25 Contacts Report...")
    print("=" * 70)

    with iMessageDatabaseReader() as db:
        # Get all handles
        handles = db.get_all_handles()

        # Count messages per handle (1-on-1 only)
        handle_counts = []
        for i, handle in enumerate(handles):
            if i % 100 == 0:
                print(f"Processing handle {i}/{len(handles)}...")

            result = db.execute_query(
                """
                SELECT COUNT(DISTINCT m.ROWID) as count
                FROM message m
                INNER JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
                INNER JOIN chat_handle_join chj ON cmj.chat_id = chj.chat_id
                WHERE chj.handle_id = ?
                  AND (m.associated_message_type = 0 OR m.associated_message_type IS NULL)
                  AND cmj.chat_id IN (
                      SELECT chat_id
                      FROM chat_handle_join
                      GROUP BY chat_id
                      HAVING COUNT(DISTINCT handle_id) <= 2
                  )
                """,
                (handle['ROWID'],)
            )
            count = result[0]['count'] if result else 0
            if count > 0:
                handle_counts.append({
                    'handle_id': handle['ROWID'],
                    'identifier': handle['id'],
                    'count': count
                })

        # Sort by message count
        handle_counts.sort(key=lambda x: x['count'], reverse=True)

        print(f"\nAnalyzing top 25 contacts...")

        # Analyze top 25
        report_data = []
        analyzed_count = 0

        for i, handle_info in enumerate(handle_counts):
            if analyzed_count >= 25:
                break

            print(f"  {analyzed_count + 1}/25: {handle_info['identifier']}...")

            result = analyze_contact_for_report(
                db,
                handle_info['handle_id'],
                handle_info['identifier']
            )

            if result:
                result['rank'] = analyzed_count + 1
                report_data.append(result)
                analyzed_count += 1

    # Save to JSON
    output_file = Path(__file__).parent / "docs" / "data.json"
    output_file.parent.mkdir(exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Generated report with {len(report_data)} contacts")
    print(f"✓ Saved to: {output_file}")

    # Print summary
    print("\n" + "=" * 70)
    print("TOP 25 CONTACTS SUMMARY")
    print("=" * 70)

    for contact in report_data:
        print(f"\n{contact['rank']}. {contact['name']}")
        print(f"   Messages: {contact['total_messages']} | Sessions: {contact['sessions']}")
        if contact['message_ratio']:
            print(f"   You send: {contact['message_ratio']:.1%} | They initiate: {contact['initiator_ratio']:.1%}" if contact['initiator_ratio'] else "")
        print(f"   Streak: {contact['current_streak']} days (longest: {contact['longest_streak']})")


if __name__ == "__main__":
    main()
