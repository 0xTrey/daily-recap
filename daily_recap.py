#!/usr/bin/env python3
"""
Daily Recap - Main Orchestrator

Collects data from Gmail, Calendar, Google Tasks, Stage 1 JSON (Granola + Slack),
enriches Granola via granola_reader, extracts tasks via LLM, tracks companies,
and prepends a prioritized section to a running Google Doc with local backup.

Usage:
    python daily_recap.py              # Normal run
    python daily_recap.py --dry-run    # Print to stdout, don't write to doc
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.gmail_fetcher import fetch_and_classify
from src.calendar_fetcher import fetch_all_events
from src.gdoc_manager import get_or_create_doc, read_doc_body, extract_carryover_tasks, prepend_daily_section
from src.task_extractor import extract_tasks, extract_activity, extract_waiting_on, deduplicate_tasks, format_tasks_for_doc
from src.tasks_fetcher import fetch_all_tasks, get_overdue_tasks, get_due_soon_tasks, format_tasks_for_prompt
from src.granola_enricher import enrich_granola_data
from src.company_tracker import extract_companies, format_companies_for_doc
from src.local_backup import save_daily_backup


def load_config() -> dict:
    settings_path = PROJECT_ROOT / "config" / "settings.json"
    with open(settings_path) as f:
        return json.load(f)


def setup_logging(log_path: str):
    """Configure logging to both stdout and file."""
    log_file = Path(log_path).expanduser()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = logging.FileHandler(str(log_file), mode="a")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)


def get_lookback_range() -> tuple[datetime, datetime]:
    """
    Calculate the lookback time range.

    Default: 36 hours back for calendar, 48 hours for email.
    Monday exception: extend back to Friday 9am to cover the weekend.

    Returns (start, end) as UTC-naive datetimes.
    """
    now = datetime.utcnow()
    end = now

    if now.weekday() == 0:  # Monday
        days_back = 3
        friday = now - timedelta(days=days_back)
        start = friday.replace(hour=15, minute=0, second=0, microsecond=0)
    else:
        start = now - timedelta(hours=48)

    return start, end


def load_stage1_json(path: str) -> tuple[dict, dict]:
    """
    Load Stage 1 JSON (Granola + Slack data).
    Returns (granola_data, slack_data). Returns empty dicts if file missing.
    """
    logger = logging.getLogger(__name__)
    json_path = Path(path).expanduser()

    if not json_path.exists():
        logger.warning(f"Stage 1 JSON not found at {json_path}. Continuing without Granola/Slack data.")
        return {}, {}

    try:
        with open(json_path) as f:
            data = json.load(f)

        granola = data.get("granola", {})
        slack = data.get("slack", {})
        collected_at = data.get("collected_at", "unknown")
        logger.info(f"Loaded Stage 1 JSON (collected at {collected_at}): {len(granola.get('meetings', []))} meetings, {len(slack.get('messages', []))} slack messages")
        return granola, slack
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to parse Stage 1 JSON: {e}. Continuing without it.")
        return {}, {}


def fetch_gmail_with_retry(start: datetime, end: datetime) -> list[dict]:
    """Fetch Gmail threads with one retry on failure."""
    logger = logging.getLogger(__name__)

    try:
        return fetch_and_classify(start, end)
    except Exception as e:
        logger.warning(f"Gmail fetch failed: {e}. Retrying in 10 minutes...")
        time.sleep(600)
        try:
            return fetch_and_classify(start, end)
        except Exception as e2:
            logger.error(f"Gmail fetch failed on retry: {e2}. Continuing without email data.")
            return []


def main():
    parser = argparse.ArgumentParser(description="Daily Recap")
    parser.add_argument("--dry-run", action="store_true", help="Print output to stdout instead of writing to doc")
    args = parser.parse_args()

    config = load_config()
    setup_logging(config.get("log_path", "~/Documents/daily-recap.log"))

    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("Daily Recap starting")
    logger.info("=" * 60)

    # 1. Determine lookback range
    start, end = get_lookback_range()
    logger.info(f"Lookback range: {start.isoformat()} to {end.isoformat()}")
    is_monday = datetime.now().weekday() == 0
    if is_monday:
        logger.info("Monday detected - extended lookback to Friday 9am")

    # 2. Load Stage 1 JSON
    granola, slack = load_stage1_json(config.get("stage1_json_path", "~/Documents/daily-recap-data.json"))

    # 3. Enrich Granola via granola_reader
    logger.info("Enriching Granola data via granola_reader...")
    target_date = datetime.now()
    granola = enrich_granola_data(granola, target_date)

    # 4. Fetch Gmail
    logger.info("Fetching Gmail threads...")
    emails = fetch_gmail_with_retry(start, end)
    logger.info(f"Got {len(emails)} email threads")

    # 5. Fetch Calendar
    logger.info("Fetching calendar events...")
    try:
        events = fetch_all_events(start, end)
    except Exception as e:
        logger.error(f"Calendar fetch failed: {e}. Continuing without calendar data.")
        events = []
    logger.info(f"Got {len(events)} calendar events")

    # 6. Fetch Google Tasks
    logger.info("Fetching Google Tasks...")
    all_google_tasks = fetch_all_tasks()
    overdue_tasks = get_overdue_tasks(all_google_tasks)
    due_soon_tasks = get_due_soon_tasks(all_google_tasks)
    google_tasks_prompt = format_tasks_for_prompt(overdue_tasks, due_soon_tasks)
    logger.info(f"Google Tasks: {len(overdue_tasks)} overdue, {len(due_soon_tasks)} due soon")

    # 7. Get or create Google Doc and extract carryover
    carryover = []
    if not args.dry_run:
        logger.info("Getting Google Doc...")
        doc_id, doc_url = get_or_create_doc()
        logger.info(f"Doc: {doc_url}")

        logger.info("Extracting carryover tasks...")
        full_text, _ = read_doc_body(doc_id)
        carryover = extract_carryover_tasks(full_text)
    else:
        logger.info("Dry run - skipping doc access")

    # 8. Extract tasks via LLM (now includes Google Tasks in prompt)
    manager_names = config.get("manager_names", ["Luke"])

    logger.info("Extracting tasks via LLM...")
    tasks = extract_tasks(emails, events, granola, slack, manager_names, google_tasks=google_tasks_prompt)

    logger.info("Deduplicating tasks...")
    tasks = deduplicate_tasks(tasks)
    logger.info(f"Final task count: {len(tasks)}")

    # 9. Extract activity summary and waiting-on items
    logger.info("Generating activity summary...")
    activity_text = extract_activity(emails, events, granola, slack)

    logger.info("Generating waiting-on items...")
    waiting_text = extract_waiting_on(emails, events, granola, slack)

    # 10. Extract companies (post-LLM, from all sources)
    logger.info("Extracting company engagement...")
    internal_domain = config.get("internal_domain", "folloze.com")
    ignored_domains = set(config.get("ignored_domains", []))
    companies = extract_companies(emails, events, granola, slack, internal_domain, ignored_domains)
    companies_text = format_companies_for_doc(companies)
    logger.info(f"Found {len(companies)} external companies")

    # 11. Format the daily section (with companies + overdue safety net)
    today = datetime.now()
    section_text = format_tasks_for_doc(
        tasks, carryover, activity_text, waiting_text, today,
        companies_text=companies_text,
        overdue_safety_net=overdue_tasks,
    )

    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN OUTPUT")
        print("=" * 60)
        print(section_text)
        print("=" * 60)

        print("\nExtracted tasks (raw):")
        for t in tasks:
            print(f"  [{t['category']}] {t['task']} (source: {t['source']})")

        if carryover:
            print(f"\nCarryover tasks: {len(carryover)}")
            for c in carryover:
                print(f"  - {c['task']} (from {c['original_date']})")

        if companies:
            print(f"\nCompanies engaged: {len(companies)}")
            for domain, count in list(companies.items())[:10]:
                print(f"  - {domain} ({count})")

        if overdue_tasks:
            print(f"\nOverdue Google Tasks: {len(overdue_tasks)}")
            for ot in overdue_tasks:
                print(f"  - {ot['title']} (due {ot.get('due', '')[:10]})")
    else:
        # 12. Prepend to running doc
        logger.info("Prepending section to Google Doc...")
        prepend_daily_section(doc_id, section_text)
        logger.info(f"Done. Doc updated: {doc_url}")

    # 13. Save local JSON backup
    logger.info("Saving local backup...")
    backup_data = {
        "date": today.strftime("%Y-%m-%d"),
        "emails_count": len(emails),
        "events_count": len(events),
        "granola_meetings_count": len(granola.get("meetings", [])),
        "slack_messages_count": len(slack.get("messages", [])),
        "google_tasks_count": len(all_google_tasks),
        "overdue_tasks_count": len(overdue_tasks),
        "extracted_tasks": tasks,
        "companies": companies,
        "carryover": carryover,
    }
    backup_dir = config.get("local_backup_dir", "~/.openclaw/daily-sync")
    save_daily_backup(backup_data, section_text, today, backup_dir)

    logger.info("Daily Recap complete")


if __name__ == "__main__":
    main()
