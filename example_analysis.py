#!/usr/bin/env python3
"""
Example: Complete iMessage analysis pipeline.

This script demonstrates how to:
1. Load messages from chat.db
2. Filter spam/notifications
3. Apply additional filters (transient, dormant, etc.)
4. Segment into sessions
5. Compute relationship statistics
"""

import sys
from pathlib import Path
from typing import Dict, List, Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.db.reader import iMessageDatabaseReader
from src.utils.config import get_config
from src.utils.contacts import get_contact_name
from src.filters.spam import SpamDetector
from src.filters.additional import FilterPipeline
from src.analysis.sessions import assign_sessions
from src.analysis.stats import compute_all_stats


def analyze_contact(handle_id: str, handle_identifier: str) -> Dict[str, Any]:
    """
    Run complete analysis pipeline for a single contact.

    Args:
        handle_id: The ROWID from the handle table
        handle_identifier: The phone number or email for display

    Returns:
        Dictionary with analysis results
    """
    # Resolve contact name
    contact_name = get_contact_name(handle_identifier)
    display = f"{contact_name} ({handle_identifier})" if contact_name else handle_identifier

    print(f"\nAnalyzing contact: {display}")
    print("-" * 50)

    with iMessageDatabaseReader() as db:
        # 1. Load all messages for this contact
        messages = db.get_messages_for_handle(handle_id)
        print(f"1. Loaded {len(messages)} messages")

        if not messages:
            return {"error": "No messages found"}

        # 2. Spam detection
        config = get_config()
        spam_detector = SpamDetector()

        # Auto-whitelist if contact has a name (they're in your contacts)
        if contact_name:
            spam_result = {
                'contact_id': handle_identifier,
                'classification': 'human',
                'confidence': 0.0,
                'is_spam': False,
                'signals': {'auto_whitelisted': 'has_contact_name'}
            }
        else:
            spam_result = spam_detector.detect(handle_identifier, messages)

        print(f"2. Spam detection: {spam_result['classification']}")
        print(f"   Confidence: {spam_result['confidence']:.2f}")

        if spam_result['classification'] == 'spam':
            print("   ⚠️  Contact classified as spam/notification - skipping")
            return {"classification": "spam", "spam_result": spam_result}

        # 3. Additional filters (skip spam filter since we already did it)
        # Create a dummy spam detector that always passes for the pipeline
        class PassthroughSpamDetector:
            def detect(self, contact_id, messages):
                return {'is_spam': False, 'classification': 'human', 'confidence': 0.0}

        filter_pipeline = FilterPipeline(PassthroughSpamDetector(), None)
        # Need to segment into sessions first for the filter pipeline
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
            messages,  # Using same list for both since messages already exclude tapbacks
            sessions_dict
        )

        print(f"3. Filter pipeline: {filter_result['final_action']}")
        if filter_result['final_action'] in ['exclude', 'defer']:
            print(f"   Reason: {filter_result.get('reason', 'N/A')}")
            return {"classification": filter_result['final_action'], "filter_result": filter_result}

        # 4. Session segmentation
        messages_with_sessions = assign_sessions(messages)
        num_sessions = len(set(msg['session_id'] for msg in messages_with_sessions))
        print(f"4. Segmented into {num_sessions} sessions (4-hour gap threshold)")

        # 5. Compute all statistics
        stats = compute_all_stats(messages_with_sessions)
        print(f"5. Computed statistics:")
        print(f"   - Total messages: {stats['volume']['total_messages']}")
        if stats['volume']['message_ratio'] is not None:
            print(f"   - Message ratio (you): {stats['volume']['message_ratio']:.2%}")
        if stats['volume']['word_ratio'] is not None:
            print(f"   - Word ratio (you): {stats['volume']['word_ratio']:.2%}")

        if stats.get('response_times'):
            rt = stats['response_times']
            if rt.get('median_my_rt'):
                print(f"   - Your median response time: {rt['median_my_rt']/60:.1f} minutes")
            if rt.get('median_their_rt'):
                print(f"   - Their median response time: {rt['median_their_rt']/60:.1f} minutes")

        if stats.get('initiator_ratio') is not None:
            print(f"   - Initiator ratio (they start): {stats['initiator_ratio']:.2%}")

        if stats.get('reciprocity') is not None:
            print(f"   - Reciprocity score: {stats['reciprocity']:.2f}")

        if stats.get('conversation_depth'):
            depth = stats['conversation_depth']
            print(f"   - Avg messages/session: {depth['avg_messages_per_session']:.1f}")

        if stats.get('streaks'):
            streaks = stats['streaks']
            print(f"   - Longest streak: {streaks.get('longest_streak', 0)} days")
            print(f"   - Current streak: {streaks.get('current_streak', 0)} days")

        return {
            "classification": "analyzed",
            "messages": len(messages),
            "sessions": num_sessions,
            "stats": stats,
            "spam_result": spam_result,
            "filter_result": filter_result
        }


def analyze_top_contacts(limit: int = 10):
    """
    Analyze top N contacts by message volume.

    Args:
        limit: Number of top contacts to analyze
    """
    print("=" * 50)
    print(f"iMessage Analysis: Top {limit} Contacts")
    print("=" * 50)

    with iMessageDatabaseReader() as db:
        # Get all handles
        handles = db.get_all_handles()
        print(f"\nTotal contacts in database: {len(handles)}")

        # Count messages per handle using chat joins (1-on-1 only)
        handle_counts = []
        for handle in handles:
            result = db.execute_query(
                """
                SELECT COUNT(DISTINCT m.ROWID) as count
                FROM message m
                INNER JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
                INNER JOIN chat_handle_join chj ON cmj.chat_id = chj.chat_id
                WHERE chj.handle_id = ?
                  AND (m.associated_message_type = 0 OR m.associated_message_type IS NULL)
                  AND cmj.chat_id IN (
                      -- Only 1-on-1 chats (1-2 participants)
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

        # Analyze top N
        results = []
        for i, handle_info in enumerate(handle_counts[:limit], 1):
            print(f"\n{'=' * 50}")
            print(f"Contact #{i}")
            result = analyze_contact(handle_info['handle_id'], handle_info['identifier'])
            results.append({
                'rank': i,
                'identifier': handle_info['identifier'],
                'message_count': handle_info['count'],
                'analysis': result
            })

        # Summary
        print("\n" + "=" * 50)
        print("ANALYSIS SUMMARY")
        print("=" * 50)

        analyzed = sum(1 for r in results if r['analysis']['classification'] == 'analyzed')
        spam = sum(1 for r in results if r['analysis']['classification'] == 'spam')
        excluded = sum(1 for r in results if r['analysis']['classification'] in ['exclude', 'defer'])

        print(f"\nAnalyzed: {analyzed}")
        print(f"Spam/Notifications: {spam}")
        print(f"Excluded/Deferred: {excluded}")

        return results


if __name__ == "__main__":
    # Analyze top 10 contacts by message volume
    analyze_top_contacts(limit=10)
