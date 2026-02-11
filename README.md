# daily-recap

Automated daily activity pipeline that pulls from five data sources, extracts tasks via LLM, deduplicates across sources, and maintains a running Google Doc with carryover tracking.

Built for sales professionals who need a single prioritized view of what happened today and what needs doing tomorrow.

## Data sources

| Source | What it captures |
|---|---|
| Gmail | Inbox threads with reply status (unread, read, replied) |
| Google Calendar | All timed events, tagged internal vs external |
| Google Tasks | Overdue and due-soon items across all task lists |
| Granola | Meeting notes, AI summaries, attendees, action items (via local cache) |
| Slack | Messages sent to and from you (via MCP in Stage 1) |

## How it works

The pipeline runs in two stages:

**Stage 1** (Claude Code skill `/daily-recap`): Collects Granola meetings and Slack messages via MCP tools, writes them to `~/Documents/daily-recap-data.json`.

**Stage 2** (this Python pipeline): Reads Stage 1 JSON, fetches Gmail/Calendar/Tasks directly, runs LLM extraction, and writes the result to a running Google Doc.

Full flow:

1. Load config and calculate lookback range (48h, or back to Friday 9am on Mondays)
2. Load Stage 1 JSON (Granola + Slack)
3. Enrich Granola data via `granola_reader` (adds AI panels, user notes, attendee emails)
4. Fetch Gmail inbox threads
5. Fetch Calendar events
6. Fetch Google Tasks (overdue + due within 2 days)
7. Extract carryover tasks from previous day's doc section
8. LLM task extraction from all sources (structured JSON output)
9. Fuzzy deduplication across sources (rapidfuzz, 85% threshold)
10. Generate activity summary, waiting-on items, and company engagement
11. Format everything into a markdown section
12. Prepend to running Google Doc (newest at top)
13. Save local JSON + markdown backup to `~/.openclaw/daily-sync/`

## Output format

Each day's section in the running doc:

```
## 2026-02-10 - Daily Recap

### What I did today
- Attended demo call with Acme, discussed pricing (calendar)
- Replied to 3 email threads (email)

### What needs doing

#### Luke requests
[ ] Review Q1 deck (by 2026-02-11) - Folloze (email)

#### Internal
[ ] Complete annual review (by 2026-02-08) - (google_tasks, overdue)

#### External
[ ] Send updated proposal to Acme (by 2026-02-12) - Acme (granola)

### Waiting on
- Acme: signed SOW (sent 02/05)

### Companies engaged
- acme.com (5 interactions)
- beta.io (2 interactions)

### Carried forward
[ ] [Carried from 02/09] Follow up with Beta on demo
```

## Project structure

```
daily-recap/
  daily_recap.py            # Main orchestrator (13-step pipeline)
  config/
    settings.json           # User config (gitignored)
    settings.example.json   # Template
  src/
    gmail_fetcher.py        # Gmail inbox fetch + thread classification
    calendar_fetcher.py     # Calendar events with internal/external tagging
    tasks_fetcher.py        # Google Tasks overdue/due-soon detection
    granola_enricher.py     # Merges MCP data with granola_reader digest
    company_tracker.py      # Domain extraction from all sources
    task_extractor.py       # LLM extraction, dedup, formatting
    gdoc_manager.py         # Running doc management (prepend, carryover)
    local_backup.py         # JSON + markdown backup
    llm_client.py           # LLMGateway wrapper with 3-tier fallback
  tests/
    test_task_extractor.py
    test_tasks_fetcher.py
    test_company_tracker.py
    test_granola_enricher.py
    test_gdoc_manager.py
    test_gmail_fetcher.py
    test_calendar_fetcher.py
```

## Dependencies

This project uses three shared libraries (all installed via `pip install -e`):

- [google-workspace](https://github.com/0xTrey/google-workspace) - Centralized Google OAuth2 and API wrappers (Calendar, Gmail, Docs, Drive, Tasks)
- [granola-reader](https://github.com/0xTrey/granola-reader) - Reads Granola's local Electron cache for meeting notes, panels, and transcripts
- [llm-gateway](https://github.com/0xTrey/llm-gateway) - LLM routing with profile-based fallback chains

Other dependencies: `rapidfuzz` (fuzzy dedup), `python-dateutil` (date parsing).

## Setup

1. Install shared libraries:
   ```bash
   pip install -e ~/Projects/google-workspace
   pip install -e ~/Projects/granola-reader
   pip install -e ~/Projects/llm-gateway
   ```

2. Authenticate with Google (includes Tasks scope):
   ```bash
   python -m google_workspace.setup_auth
   ```

3. Copy and edit config:
   ```bash
   cp config/settings.example.json config/settings.json
   # Edit with your doc_id, internal_domain, manager_names
   ```

4. Run:
   ```bash
   python daily_recap.py --dry-run    # Preview output
   python daily_recap.py              # Write to Google Doc
   ```

## Configuration

`config/settings.json` (gitignored):

| Key | Description |
|---|---|
| `internal_domain` | Your company domain (e.g. `folloze.com`) |
| `manager_names` | Names for manager-priority task categorization |
| `doc_id` | Google Doc ID for the running log |
| `stage1_json_path` | Path to Stage 1 JSON (default: `~/Documents/daily-recap-data.json`) |
| `local_backup_dir` | Backup directory (default: `~/.openclaw/daily-sync`) |
| `ignored_domains` | Additional domains to exclude from company tracking |
| `max_carryover_days` | Drop carried tasks older than this (default: 7) |

## LLM routing

Task extraction uses a three-tier fallback via LLMGateway:

1. `strategic` (Gemini 2.5 Flash) - primary
2. `local` (Ollama / Qwen) - local fallback
3. `nvidia` (NVIDIA API / Kimi K2.5) - cloud fallback

## Tests

```bash
cd ~/Projects/daily-recap
pytest                  # 72 tests
pytest -v               # Verbose output
```

## History

This system consolidates two earlier projects:

- **daily-recap** (original) - LLM-powered task extraction with fuzzy dedup, carryover tracking, and a running Google Doc. Had Gmail, Calendar, Granola (via JSON), and Slack (via JSON). Missing Google Tasks, company tracking, and local backups.
- **nightly-sync** (retired) - Pattern-based task extraction with single-day scope. Had Gmail, Calendar, Google Tasks, Granola (via granola_reader), and company tracking. Missing LLM extraction, dedup, carryover, and Slack.

The consolidated system keeps daily-recap's architecture (LLM extraction, dedup, carryover, running doc, modular tests) and adds nightly-sync's features (Google Tasks, company tracking, local backups, granola_reader enrichment). nightly-sync has been deprecated.
