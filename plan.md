# iMessage Parser — MVP Spec

## Overview

A local Mac app/CLI that reads the native iMessage SQLite database and generates relationship stats, visualizations, and a foundation for a personal knowledge vault. All processing happens on-device. Nothing leaves the machine.

---

## Data Source: `chat.db`

Located at `~/Library/Messages/chat.db`. Standard SQLite — readable with any SQLite client or the `sqlite3` Python module. Full disk access permission required on macOS (System Settings → Privacy & Security → Full Disk Access).

### Core Tables

#### `message`
The central table. One row per message.

| Column | Type | Notes |
|--------|------|-------|
| `ROWID` | INTEGER | Primary key |
| `guid` | TEXT | Globally unique message ID |
| `text` | TEXT | Message body (null for media-only) |
| `handle_id` | INTEGER | FK → `handle.ROWID` (0 if sent by you) |
| `date` | INTEGER | **Nanoseconds since 2001-01-01** (not Unix epoch — see below) |
| `date_delivered` | INTEGER | When delivered |
| `date_read` | INTEGER | When read |
| `is_from_me` | INTEGER | 1 = sent by you, 0 = received |
| `cache_has_attachments` | INTEGER | 1 = has attachment |
| `associated_message_guid` | TEXT | Non-null = this is a reaction/tapback |
| `associated_message_type` | INTEGER | Tapback type (1000=heart, 2000=thumbs up, etc.) |
| `reply_to_guid` | TEXT | Thread reply reference |
| `is_read` | INTEGER | Read receipt |
| `service` | TEXT | "iMessage" or "SMS" |

**Date conversion — critical:**
```python
import datetime
# Apple epoch starts 2001-01-01, not 1970-01-01
APPLE_EPOCH_OFFSET = 978307200  # seconds between 1970 and 2001
def apple_to_unix(apple_ts):
    return (apple_ts / 1e9) + APPLE_EPOCH_OFFSET

def apple_to_datetime(apple_ts):
    return datetime.datetime.fromtimestamp(apple_to_unix(apple_ts))
```

#### `handle`
Maps `handle_id` to a phone number or email.

| Column | Type | Notes |
|--------|------|-------|
| `ROWID` | INTEGER | PK |
| `id` | TEXT | Phone number (+1XXXXXXXXXX) or email |
| `country` | TEXT | e.g. "us" |
| `service` | TEXT | "iMessage" or "SMS" |

**You (is_from_me=1) have no handle row.** Your messages are identified solely by `is_from_me = 1`.

#### `chat`
Represents a conversation thread (1:1 or group).

| Column | Type | Notes |
|--------|------|-------|
| `ROWID` | INTEGER | PK |
| `guid` | TEXT | e.g. "iMessage;-;+1XXXXXXXXXX" |
| `chat_identifier` | TEXT | Phone/email for 1:1, group ID for groups |
| `display_name` | TEXT | Set for group chats, null for 1:1 |
| `group_id` | TEXT | Non-null = group chat |
| `is_archived` | INTEGER | |

#### `chat_message_join`
Many-to-many join between chats and messages.

| Column | Type |
|--------|------|
| `chat_id` | INTEGER → `chat.ROWID` |
| `message_id` | INTEGER → `message.ROWID` |

#### `attachment`
| Column | Type | Notes |
|--------|------|-------|
| `ROWID` | INTEGER | |
| `guid` | TEXT | |
| `filename` | TEXT | Local path to file |
| `mime_type` | TEXT | e.g. "image/jpeg" |
| `total_bytes` | INTEGER | |

#### `message_attachment_join`
Join between messages and attachments.

---

### Key Gotchas

1. **Date is nanoseconds since 2001-01-01**, not Unix milliseconds or seconds. Easy to miss.
2. **Reactions (tapbacks) are stored as messages** with `associated_message_guid` set. Filter these out when counting "real" messages: `WHERE associated_message_type = 0`.
3. **Group chats**: a `chat` with multiple `handle`s joined via `chat_handle_join`. For MVP, filter to 1:1 only (`WHERE display_name IS NULL`).
4. **Deleted messages**: rows may remain with `text = NULL` and no attachment. Handle gracefully.
5. **Phone number normalization**: the same contact may appear as `+12025551234`, `2025551234`, or `(202) 555-1234` across different handles. Normalize to E.164 before grouping.
6. **Contact name resolution**: `chat.db` does not store display names for 1:1 contacts. You must cross-reference with macOS Contacts via `CNContactStore` (Swift) or `Contacts` framework, or use `AddressBook` via Python's `objc` bridge.

---

## Session Definition

A **session** is a continuous exchange where no gap between consecutive messages exceeds **4 hours**.

```python
SESSION_GAP_SECONDS = 4 * 60 * 60

def assign_sessions(messages):
    """
    messages: list of dicts sorted by date asc, for one contact
    Returns messages with session_id assigned
    """
    session_id = 0
    for i, msg in enumerate(messages):
        if i == 0:
            msg['session_id'] = session_id
            continue
        gap = msg['date_unix'] - messages[i-1]['date_unix']
        if gap > SESSION_GAP_SECONDS:
            session_id += 1
        msg['session_id'] = session_id
    return messages
```

Sessions are the unit for: response time, initiator ratio, depth, streak calculation.

---

## Stats Definitions

### 1. Volume

| Stat | Formula |
|------|---------|
| `total_messages` | COUNT(*) across all time |
| `messages_from_me` | COUNT WHERE is_from_me = 1 |
| `messages_from_them` | COUNT WHERE is_from_me = 0 |
| `message_ratio` | messages_from_me / total_messages |
| `total_words_me` | SUM(word_count) WHERE is_from_me = 1 |
| `total_words_them` | SUM(word_count) WHERE is_from_me = 0 |
| `word_ratio` | total_words_me / (total_words_me + total_words_them) |

Word ratio is more honest than message ratio — one-word replies skew message counts.

---

### 2. Response Time

**Definition:** time between the last message of person X's "turn" and the first message of person Y's reply, within the same session. Cross-session replies are excluded.

A **turn** ends when the other person starts speaking (or the session ends).

```python
def compute_response_times(session_messages):
    """Returns (my_response_times, their_response_times) in seconds"""
    my_rts, their_rts = [], []
    i = 0
    while i < len(session_messages):
        # Find end of current speaker's burst
        current_speaker = session_messages[i]['is_from_me']
        burst_end_time = session_messages[i]['date_unix']
        j = i
        while j < len(session_messages) and session_messages[j]['is_from_me'] == current_speaker:
            burst_end_time = session_messages[j]['date_unix']
            j += 1
        if j < len(session_messages):
            response_time = session_messages[j]['date_unix'] - burst_end_time
            if current_speaker == 1:  # I spoke, they responded
                their_rts.append(response_time)
            else:  # They spoke, I responded
                my_rts.append(response_time)
        i = j
    return my_rts, their_rts
```

**Output:** median (not mean) response time in each direction. Use median to remove outliers (fell asleep, forgot to reply, etc.).

---

### 3. Initiator Ratio

**Definition:** per session, the initiator is whoever sends the first message. Initiator ratio = sessions they started / total sessions.

- **> 0.6**: they seek you out more
- **~0.5**: balanced
- **< 0.4**: you're usually pulling the relationship

Edge case: if both parties send a message within 3 minutes of a session start, call it a co-initiation and exclude from ratio calculation.

---

### 4. Reciprocity Score

```python
reciprocity = min(words_me, words_them) / max(words_me, words_them)
```

Range 0–1. Score of 1.0 = perfectly balanced word output. Score of 0.3 = one person writes 3× more.

Compute per-session and report as a distribution (median + IQR), not just an average.

---

### 5. Ghost Rate

**Definition:** percentage of your message bursts (at end of your turn, ending a session) that received no reply within 48 hours. Compute symmetrically for their ghost rate toward you.

```python
def ghost_rate(sessions, direction='me'):
    """direction: 'me' = sessions where I had last word with no reply"""
    ghosted = 0
    total = 0
    for session in sessions:
        last_msg = session[-1]
        next_session_start = ...  # first msg of next session
        if last_msg['is_from_me'] == (1 if direction == 'me' else 0):
            total += 1
            time_to_reply = next_session_start['date_unix'] - last_msg['date_unix']
            if time_to_reply > 48 * 3600 or next_session_start is None:
                ghosted += 1
    return ghosted / total if total > 0 else None
```

---

### 6. Response Time Asymmetry Over Time

**The high-signal stat.** Compute `(median_my_RT - median_their_RT)` per rolling 90-day window. Plot as a line over time.

- Positive drift → you're becoming more responsive than they are (relationship cooling on their side)
- Negative drift → they're chasing you more
- Flat near zero → sustained healthy mutual investment

---

### 7. Conversation Depth

| Stat | Formula |
|------|---------|
| `avg_messages_per_session` | total_messages / total_sessions |
| `avg_words_per_session` | total_words / total_sessions |
| `depth_variance` | std dev of messages-per-session |

High variance = bimodal relationship (quick logistics OR deep conversation, nothing in between).

---

### 8. Message Length

| Stat | Notes |
|------|-------|
| Median message length (words), per direction | Filter out tapbacks and empty messages |
| Length adaptation score | Pearson correlation between consecutive message lengths in a session |

Length adaptation: if your messages get longer when theirs do and shorter when theirs do, score approaches 1. People who mirror each other's verbosity tend to be more in sync.

---

### 9. Streak & Cadence (GitHub-style Heatmap)

**Streak:** consecutive calendar days with at least one session.
- Longest streak (all time)
- Current streak

**Cadence:** median days between session starts, trailing 90 days.

**Heatmap:** GitHub contribution graph layout — 52 columns (weeks) × 7 rows (days). Each cell shaded by message volume that day, 5 intensity levels (0, 1–2, 3–5, 6–10, 11+). Color palette: GitHub green (`#ebedf0`, `#9be9a8`, `#40c463`, `#30a14e`, `#216e39`).

Per-contact heatmap showing communication density over the trailing 12 months.

---

### 10. Time-of-Day Profile

Bucket messages into 4 windows (local time):
- Morning: 06:00–12:00
- Afternoon: 12:00–18:00  
- Evening: 18:00–23:00
- Late Night: 23:00–06:00

Express as % distribution per contact. Surface which contacts are exclusively daytime vs late-night.

Also generate a global heatmap: hour of day (0–23) × day of week (Mon–Sun), shaded by message volume. Shows your personal messaging circadian rhythm.

---

## Importance Heuristic (bridge to Phase 2)

Score per contact, range 0–100, weighted sum of:

| Signal | Weight | Rationale |
|--------|--------|-----------|
| Recency (days since last session, decayed) | 25% | Dormant relationships score lower |
| Volume (trailing 90d, normalized) | 20% | Raw activity |
| Session depth (avg messages/session) | 15% | Depth over breadth |
| Reciprocity score | 15% | Balanced = more substantive |
| Response urgency (% replies < 5 min) | 15% | Fast replies = high investment |
| Initiator balance (closeness to 0.5) | 10% | Mutual vs one-sided |

Score per message cluster (session):
- Session length
- Response urgency within session
- Keyword density: questions, proper nouns, dates, dollar amounts, addresses
- Sentiment markers (basic lexicon lookup)

---

## Spam / Notification Filter

Applied before any stat computation. Contacts that pass the spam filter are excluded entirely from the dashboard and importance scoring.

### Detection Signals

A contact is flagged as spam/notification if **any** of the following are true:

| Rule | Threshold | Examples caught |
|------|-----------|----------------|
| **One-sided volume** | ≥ 20 messages from them, 0 replies from you, ever | Delivery notifications, bank alerts |
| **Zero-reply streaks** | ≥ 10 consecutive messages from them with no reply in between | Promo blasts |
| **Message velocity** | ≥ 5 messages from them within 10 minutes, no reply | OTP floods, order updates |
| **Short message uniformity** | ≥ 80% of messages under 12 words AND std dev of message length < 3 | Templated notifications |
| **Keyword patterns** | Message text matches notification regex patterns (see below) | Verification codes, tracking |
| **Handle format** | `handle.id` is a short alphanumeric sender ID (not a phone/email) | e.g. "AMZN", "DoorDash", "Chase" |

### Notification Regex Patterns

```python
SPAM_PATTERNS = [
    r'\b\d{4,8}\b.*\b(code|pin|otp|verify|verification)\b',  # OTP codes
    r'\btrack(ing)?\b.*\border\b',                             # Order tracking
    r'\bdelivered\b|\bout for delivery\b|\barriving\b',        # Delivery status
    r'\byour (order|package|shipment)\b',                      # Order updates
    r'\breply stop to (opt.?out|unsubscribe)\b',               # Marketing
    r'\b(promo|offer|deal|discount|% off|save \$)\b',          # Promotions
    r'\bappointment (reminder|confirmed|scheduled)\b',          # Appointments
    r'\bstatement (ready|available)\b|\bpayment due\b',        # Bank/billing
]
```

### Scoring Approach

Rather than a hard binary, assign a **spam confidence score** (0.0–1.0) using a weighted sum of triggered signals. This allows for a UI that shows borderline cases separately (e.g. a contact you text occasionally but who also sends you promos).

```python
SPAM_WEIGHTS = {
    'zero_reply_ever':       0.6,   # Strong signal on its own
    'zero_reply_streak':     0.4,
    'high_velocity':         0.3,
    'length_uniformity':     0.3,
    'keyword_match':         0.4,   # Per pattern matched, capped at 0.4
    'alphanumeric_sender':   0.5,   # Short sender IDs are almost always services
}

# Classify:
# >= 0.7 → spam (excluded from all stats)
# 0.4–0.7 → borderline (flagged, shown separately, user can override)
# < 0.4 → human contact (included normally)
```

### User Overrides

- Maintain a **whitelist** and **blacklist** in local config (`~/.imessage-parser/config.json`)
- Any contact on the whitelist is never filtered regardless of score
- Borderline contacts surface in a review UI: "Are these human contacts?" with Accept / Reject per contact
- Overrides persist across runs

### Config Format

```json
{
  "spam_threshold": 0.7,
  "whitelist": ["+12025551234", "alerts@mybank.com"],
  "blacklist": ["DOORDASH", "UPS"],
  "session_gap_seconds": 14400
}
```

---

## Additional Filters

Applied in sequence after spam filtering. Each filter has a mode: **exclude** (drop from all analysis), **tag** (keep but flag in UI), or **defer** (separate view, not in main dashboard).

### Filter Pipeline Order

```
Raw contacts from chat.db
  → [1] Spam / notification filter       (exclude)
  → [2] Transient contact filter         (exclude or tag)
  → [3] Dormancy filter                  (exclude from active view, archive)
  → [4] Group chat filter                (defer to separate view)
  → [5] Tapback-only filter              (exclude)
  → [6] Automated regular filter         (exclude)
  → [7] SMS quality tag                  (tag only, never exclude)
  → Active human contacts → stat engine
```

---

### 1. Transient Contact Filter

**What it catches:** Uber drivers, Airbnb hosts, one-time contractors, people you texted once to coordinate something.

**Mode:** exclude from dashboard (optionally archive for Phase 2 life-event archaeology)

| Signal | Threshold |
|--------|-----------|
| Total messages (all time) | ≤ 10 |
| Time span of entire exchange | ≤ 3 days |
| Number of distinct sessions | ≤ 2 |

All three must be true. A short exchange that spans 2 weeks (e.g. planning something) is not transient.

---

### 2. Dormancy Filter

**What it catches:** contacts you were close to in a past life chapter but haven't talked to in years. They skew all-time aggregates without representing current relationships.

**Mode:** exclude from active dashboard, keep in an "archived contacts" view

| Config | Default |
|--------|---------|
| `dormancy_threshold_days` | 730 (2 years) |

A contact is dormant if their most recent message (either direction) is older than the threshold. If they were once high-volume (top 20 contacts by total messages), surface them in a "past close contacts" section rather than burying them entirely.

---

### 3. Group Chat Filter

**What it catches:** all multi-participant threads.

**Mode:** defer to a separate "Group Chats" view — not filtered permanently

**Why separate:** group chat stats need a different model entirely. Turn-taking is ambiguous (you reply to the group, not one person). Your message ratio is naturally lower. Initiator concept doesn't apply. Response time is noisy. Build this view in Phase 2.

**Detection:** `chat.display_name IS NOT NULL` OR `chat_id` has > 2 distinct handles in `chat_handle_join`.

---

### 4. Tapback-Only Filter

**What it catches:** contacts where the entire relationship is almost exclusively reactions — no real message exchange.

**Mode:** exclude

| Signal | Threshold |
|--------|-----------|
| % of messages that are tapbacks (`associated_message_type != 0`) | ≥ 80% |
| Total non-tapback messages | ≤ 5 |

Note: tapback filtering also applies at the **message level** globally before computing any stat. This filter is for contacts where removing tapbacks leaves almost nothing.

---

### 5. Automated Regular Filter

**What it catches:** services you interact with regularly (opted-in, legitimate), but that aren't human conversations. Different from spam — these may have patterned replies from you. Examples: Google Calendar SMS reminders, bank balance alerts, GitHub notifications.

**Mode:** exclude

| Signal | Threshold | Notes |
|--------|-----------|-------|
| Send-time variance | Std dev of send hour < 1.5 hrs across ≥ 20 messages | Robots send at fixed times |
| Message length variance | Std dev < 4 words across all messages | Templated content |
| You-initiated ratio | < 5% | You almost never start these |

Combine: flag if send-time variance AND length variance are both below threshold.

---

### 6. SMS Quality Tag

**What it catches:** real contacts whose messages came through as SMS (green bubble) rather than iMessage.

**Mode:** tag only — never exclude. Surface in UI as a data quality indicator.

SMS messages are missing:
- Reliable delivery timestamps (`date_delivered` = 0)
- Read receipts (`date_read` = 0)
- Precise send timestamps (carrier-delayed)

**Detection:** `message.service = 'SMS'`

**Effect on stats:** response time calculations for SMS contacts are marked as `low_confidence`. Ghost rate is not computed (no read receipts). All other stats are computed normally but shown with a warning indicator in the UI.

If a contact has a mix of iMessage and SMS (switched phones, traveling, etc.), compute stats separately per service type and show both.

---

### Filter Summary Table

| Filter | Mode | Primary Signal |
|--------|------|----------------|
| Spam / notification | Exclude | Zero replies + keyword patterns + sender ID format |
| Transient | Exclude | ≤ 10 messages, ≤ 3 days, ≤ 2 sessions |
| Dormant | Archive | No message in > 2 years |
| Group chat | Defer | Multiple handles in chat |
| Tapback-only | Exclude | ≥ 80% reactions, ≤ 5 real messages |
| Automated regular | Exclude | Fixed send cadence + low variance |
| SMS fallback | Tag | `service = 'SMS'` |

---

## Tech Stack (suggested)

| Layer | Choice | Notes |
|-------|--------|-------|
| DB access | Python `sqlite3` | Standard lib, no deps |
| Data processing | `pandas` | Session windowing, rolling stats |
| Contact resolution | `pyobjc` / Swift subprocess | Access macOS Contacts |
| Visualization | `recharts` (React) or `d3` | Heatmap, time-of-day radial |
| App shell | Electron or native Mac SwiftUI | Local only |
| Phase 2 vector store | `chromadb` or `lancedb` | Local embeddings |

---

## MVP Scope (v1)

- [ ] Read `chat.db` with full disk access
- [ ] Run spam filter on all contacts before any stat computation
- [ ] Normalize phone numbers, resolve contact names
- [ ] Filter to 1:1 conversations, exclude tapbacks
- [ ] Session segmentation (4h gap)
- [ ] Per-contact stats: volume, word ratio, response times, initiator ratio, reciprocity, ghost rate
- [ ] Global leaderboard / ranked contact list
- [ ] GitHub-style heatmap per contact (trailing 12 months)
- [ ] Time-of-day profile per contact
- [ ] Response time asymmetry trend line (trailing 12 months, 90d rolling window)
- [ ] Basic importance score per contact

## Phase 2 Scope

- [ ] Chunk conversation history by session into retrievable units
- [ ] Embed chunks locally (sentence-transformers or OpenAI)
- [ ] Store in local vector DB (ChromaDB / LanceDB)
- [ ] Expose as MCP server for Claude/personal assistant
- [ ] Personality fingerprint from LIWC-style dimension analysis
- [ ] Relationship map: classify contact type (planner, confidant, logistics, entertainment)
- [ ] Decision archaeology: surface sessions containing high-stakes language

---

## Privacy Notes

- All data stays local. No telemetry, no cloud sync.
- `chat.db` access requires Full Disk Access on macOS — prompt user to grant at first run.
- Optionally allow contact exclusion list (numbers/emails to never process).
- Phase 2 embeddings: use a local model by default; cloud embedding model opt-in only.