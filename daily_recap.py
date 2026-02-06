#!/usr/bin/env python3
"""
Daily Recap - Main Orchestrator

Collects data from Gmail, Calendar, and Stage 1 JSON (Granola + Slack),
extracts tasks via LLM, and prepends a prioritized section to a running Google Doc.

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
        # Go back to Friday 9am (Central = UTC-6, so 15:00 UTC)
        days_back = 3  # Monday -> Friday
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

    # Determine lookback range
    start, end = get_lookback_range()
    logger.info(f"Lookback range: {start.isoformat()} to {end.isoformat()}")
    is_monday = datetime.now().weekday() == 0
    if is_monday:
        logger.info("Monday detected - extended lookback to Friday 9am")

    # Load Stage 1 JSON
    granola, slack = load_stage1_json(config.get("stage1_json_path", "~/Documents/daily-recap-data.json"))

    # Fetch Gmail
    logger.info("Fetching Gmail threads...")
    emails = fetch_gmail_with_retry(start, end)
    logger.info(f"Got {len(emails)} email threads")

    # Fetch Calendar
    logger.info("Fetching calendar events...")
    try:
        events = fetch_all_events(start, end)
    except Exception as e:
        logger.error(f"Calendar fetch failed: {e}. Continuing without calendar data.")
        events = []
    logger.info(f"Got {len(events)} calendar events")

    # Get or create Google Doc and extract carryover
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

    # Extract tasks via LLM
    manager_names = config.get("manager_names", ["Luke"])

    logger.info("Extracting tasks via LLM...")
    tasks = extract_tasks(emails, events, granola, slack, manager_names)

    logger.info("Deduplicating tasks...")
    tasks = deduplicate_tasks(tasks)
    logger.info(f"Final task count: {len(tasks)}")

    # Extract activity summary and waiting-on items
    logger.info("Generating activity summary...")
    activity_text = extract_activity(emails, events, granola, slack)

    logger.info("Generating waiting-on items...")
    waiting_text = extract_waiting_on(emails, events, granola, slack)

    # Format the daily section
    today = datetime.now()
    section_text = format_tasks_for_doc(tasks, carryover, activity_text, waiting_text, today)

    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN OUTPUT")
        print("=" * 60)
        print(section_text)
        print("=" * 60)

        # Also print raw task data
        print("\nExtracted tasks (raw):")
        for t in tasks:
            print(f"  [{t['category']}] {t['task']} (source: {t['source']})")

        if carryover:
            print(f"\nCarryover tasks: {len(carryover)}")
            for c in carryover:
                print(f"  - {c['task']} (from {c['original_date']})")
    else:
        # Prepend to Google Doc
        logger.info("Prepending section to Google Doc...")
        prepend_daily_section(doc_id, section_text)
        logger.info(f"Done. Doc updated: {doc_url}")

    logger.info("Daily Recap complete")


if __name__ == "__main__":
    main()
