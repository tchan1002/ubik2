# iMessage Parser — Repository Documentation

## Project Overview

A local Mac app/CLI that reads the native iMessage SQLite database (`~/Library/Messages/chat.db`) and generates relationship statistics, visualizations, and a foundation for a personal knowledge vault. All processing happens on-device. Nothing leaves the machine.

**Privacy-first design**: Read-only database access, all data stays local, no telemetry or cloud sync.

## Architecture

### Core Components

1. **Database Layer** (`src/db/`)
   - `reader.py`: SQLite interface to chat.db with Apple timestamp conversion
   - Read-only access, handles Full Disk Access permissions
   - Key: Apple epoch starts 2001-01-01, not Unix 1970-01-01 (offset: 978307200 seconds)

2. **Analysis Layer** (`src/analysis/`)
   - `sessions.py`: Session segmentation with 4-hour gap threshold
   - `stats.py`: Statistical computations (volume, response time, reciprocity, etc.)

3. **Filter Layer** (`src/filters/`)
   - `spam.py`: 6-signal spam/notification detection with weighted scoring
   - `additional.py`: Transient, dormancy, group chat, tapback-only, automated, SMS filters

4. **Utilities** (`src/utils/`)
   - `config.py`: Configuration loader from `~/.imessage-parser/config.json`

## Key Concepts

### Apple Timestamp Conversion

**Critical**: iMessage dates are nanoseconds since 2001-01-01, NOT Unix epoch.

```python
APPLE_EPOCH_OFFSET = 978307200  # seconds between 1970 and 2001
def apple_to_unix(apple_ts):
    return (apple_ts / 1e9) + APPLE_EPOCH_OFFSET
```

### Session Definition

A **session** is a continuous exchange where no gap between consecutive messages exceeds 4 hours (14400 seconds). Sessions are the unit for response time, initiator ratio, depth, and streak calculations.

### Database Schema

Core tables in `chat.db`:
- `message`: One row per message (ROWID, text, handle_id, date, is_from_me, service)
- `handle`: Maps handle_id to phone/email (ROWID, id, country, service)
- `chat`: Conversation threads (ROWID, guid, display_name, group_id)
- `chat_message_join`: Many-to-many between chats and messages
- `attachment`: Media files with local paths

**Gotchas**:
- Reactions (tapbacks) are messages with `associated_message_guid` set
- `is_from_me = 1` means you sent it; these messages have `handle_id = 0`
- Group chats have `display_name IS NOT NULL`
- Deleted messages may have `text = NULL`

### Spam Detection

6 signals combined into weighted confidence score (0.0-1.0):

| Signal | Weight | Detects |
|--------|--------|---------|
| zero_reply_ever | 0.6 | ≥20 messages from them, 0 from you |
| zero_reply_streak | 0.4 | ≥10 consecutive messages |
| high_velocity | 0.3 | ≥5 messages in 10 minutes |
| length_uniformity | 0.3 | ≥80% under 12 words, stddev < 3 |
| keyword_match | 0.4 | Matches OTP/tracking/promo patterns |
| alphanumeric_sender | 0.5 | Short sender ID (not phone/email) |

Classification:
- ≥0.7: spam (excluded)
- 0.4-0.7: borderline (user review)
- <0.4: human contact

Whitelist/blacklist overrides in config.

### Filter Pipeline

Applied in sequence (after spam filtering):

1. **Transient**: ≤10 messages, ≤3 days, ≤2 sessions → exclude
2. **Dormancy**: No message in >730 days → archive
3. **Group chat**: Multiple handles → defer to separate view
4. **Tapback-only**: ≥80% reactions, ≤5 real messages → exclude
5. **Automated regular**: Fixed send cadence + low variance → exclude
6. **SMS quality**: service='SMS' → tag (impacts response time confidence)

### Statistics Computed

**Volume**: total messages, message ratio, word counts, word ratio

**Response Time**: Median time between end of one person's turn and start of reply. Uses turn-based burst detection. Computed per direction (me→them, them→me).

**Initiator Ratio**: Sessions started by them / total sessions. >0.6 = they seek you out, <0.4 = you're pulling.

**Reciprocity Score**: `min(words_me, words_them) / max(words_me, words_them)`. Range 0-1, 1.0 = perfectly balanced.

**Ghost Rate**: % of your message bursts (ending a session) that got no reply within 48 hours.

**Conversation Depth**: avg messages/session, avg words/session, variance

**Response Time Asymmetry**: `(median_my_RT - median_their_RT)` per 90-day rolling window. Plotted over time to detect relationship drift.

**Streaks**: Consecutive calendar days with ≥1 session. Longest all-time + current.

**Time-of-Day Profile**: % distribution across 4 windows (morning 6-12, afternoon 12-18, evening 18-23, late night 23-6).

## Configuration

**Location**: `~/.imessage-parser/config.json`  
**Default**: `config/default_config.json`

Key settings:
- `spam_threshold`: 0.7
- `session_gap_seconds`: 14400 (4 hours)
- `dormancy_threshold_days`: 730 (2 years)
- `whitelist` / `blacklist`: phone numbers or emails
- All filter thresholds configurable

## File Locations

- **iMessage DB**: `~/Library/Messages/chat.db` (requires Full Disk Access on macOS)
- **User config**: `~/.imessage-parser/config.json`
- **Whitelist overrides**: Stored in config.json

## Development Notes

### Testing Database Access

macOS requires Full Disk Access permission. Grant via:
System Settings → Privacy & Security → Full Disk Access → [Add Terminal or your app]

### Phone Number Normalization

Same contact may appear as `+12025551234`, `2025551234`, or `(202) 555-1234`. Always normalize to E.164 format before grouping.

### Contact Name Resolution

`chat.db` does NOT store display names for 1:1 contacts. Must cross-reference with macOS Contacts API:
- Use `pyobjc-framework-Contacts` to access `CNContactStore`
- Resolve phone/email to contact name

### Tapback Filtering

Always filter at message level before computing stats:
```sql
WHERE associated_message_type = 0
```
This excludes reactions (hearts, thumbs up, etc.) from message counts.

## Phase 2 Roadmap

Not yet implemented:
- Vector embeddings (sentence-transformers or OpenAI)
- Local vector DB (ChromaDB / LanceDB)
- MCP server for Claude integration
- Personality fingerprinting (LIWC-style)
- Relationship classification (planner, confidant, logistics)
- Decision archaeology (high-stakes language detection)

## Tech Stack

- Python 3.8+
- `sqlite3` (standard library)
- `pandas` for windowing and rolling stats
- `pyobjc-framework-Contacts` for macOS Contacts
- Future: SwiftUI or Electron for UI

## Code Style

- Type hints required for all functions
- Comprehensive docstrings explaining logic
- Handle edge cases gracefully (return None if not computable)
- Prefer median over mean for outlier resistance
- No external calls, all processing local

## Important Reminders

1. **Never write to chat.db** — read-only access only
2. **Date conversion is critical** — Apple epoch ≠ Unix epoch
3. **Filter tapbacks** before all stat calculations
4. **Median, not mean** for response times (outlier-resistant)
5. **Test with Full Disk Access** granted on macOS
6. **Privacy-first** — no telemetry, no cloud, all local
