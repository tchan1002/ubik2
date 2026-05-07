"""
Search all contacts in iMessage database.
"""

from src.db.reader import iMessageDatabaseReader


def main():
    print("Fetching all contacts from iMessage database...\n")

    try:
        with iMessageDatabaseReader() as reader:
            handles = reader.get_all_handles()

            print(f"Total contacts: {len(handles)}\n")

            # Display all handles
            for handle in handles[:50]:  # Show first 50
                print(f"ID: {handle['ROWID']:4d} | {handle['id']:40s} | Service: {handle.get('service', 'Unknown')}")

            if len(handles) > 50:
                print(f"\n... and {len(handles) - 50} more contacts")

            # Search for patterns that might match Aitana
            print("\n\nSearching for potential matches...")
            search_patterns = ['ait', 'tana', '@']

            for pattern in search_patterns:
                matches = [h for h in handles if pattern.lower() in h['id'].lower()]
                if matches:
                    print(f"\nContacts containing '{pattern}':")
                    for h in matches[:10]:
                        print(f"  - {h['id']} (ID: {h['ROWID']})")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
