# iMessage Parser — MVP

A local Mac app/CLI that reads the native iMessage SQLite database and generates relationship stats, visualizations, and a foundation for a personal knowledge vault. All processing happens on-device. Nothing leaves the machine.

## Privacy Guarantees

- **All data stays local** — no telemetry, no cloud sync
- **Read-only access** to your iMessage database
- **Optional exclusion list** for contacts you never want processed

## Requirements

- macOS (requires access to `~/Library/Messages/chat.db`)
- Python 3.8+
- **Full Disk Access permission** required (System Settings → Privacy & Security → Full Disk Access → add Terminal/your app)

## Installation

```bash
pip install -r requirements.txt
```

## Quick Start

```python
from src.db.reader import iMessageDatabaseReader
from src.analysis.sessions import assign_sessions
from src.filters.spam import SpamDetector
from src.analysis.stats import compute_all_stats

# Initialize database reader
with iMessageDatabaseReader() as db:
    # Load messages for a contact
    messages = db.get_messages_for_handle("+12025551234")
    
    # Filter spam
    detector = SpamDetector()
    if not detector.is_spam(messages):
        # Assign sessions (4-hour gap)
        messages_with_sessions = assign_sessions(messages)
        
        # Compute statistics
        stats = compute_all_stats(messages_with_sessions)
        print(stats)
```

## Configuration

Config file location: `~/.imessage-parser/config.json`

Copy from `config/default_config.json` and customize:
- `spam_threshold`: 0.7 (confidence score above which contacts are filtered)
- `session_gap_seconds`: 14400 (4 hours)
- `whitelist` / `blacklist`: phone numbers or emails to always include/exclude

## Project Structure

```
src/
├── db/          # Database access layer
├── analysis/    # Session segmentation and statistics
├── filters/     # Spam and quality filters
└── utils/       # Configuration and helpers
```

## MVP Features

- [x] Read `chat.db` with full disk access
- [x] Spam/notification filtering (6 detection signals)
- [x] Session segmentation (4-hour gap threshold)
- [x] Per-contact statistics:
  - Volume (messages, words, ratios)
  - Response times (median, per direction)
  - Initiator ratio
  - Reciprocity score
  - Ghost rate
  - Conversation depth
  - Message length analysis
  - Streaks and cadence

## Phase 2 (Upcoming)

- [ ] Vector embeddings for semantic search
- [ ] MCP server for Claude integration
- [ ] Personality fingerprinting
- [ ] Relationship classification
- [ ] Decision archaeology
