"""
Google Tasks fetcher for daily recap.

Fetches incomplete tasks via google-workspace, identifies overdue and due-soon items,
and formats them for the LLM extraction prompt.
"""

import logging
from datetime import datetime, timedelta, timezone

from google_workspace.tasks import get_all_tasks

logger = logging.getLogger(__name__)


def fetch_all_tasks() -> list[dict]:
    """Fetch all incomplete Google Tasks across all lists."""
    try:
        tasks = get_all_tasks(show_completed=False)
        logger.info(f"Fetched {len(tasks)} incomplete Google Tasks")
        return tasks
    except Exception as e:
        logger.warning(f"Failed to fetch Google Tasks: {e}")
        return []


def get_overdue_tasks(tasks: list[dict]) -> list[dict]:
    """Filter tasks that are past their due date."""
    now = datetime.now(timezone.utc)
    overdue = []

    for t in tasks:
        due = t.get("due")
        if not due:
            continue
        try:
            # Google Tasks API returns due dates as RFC 3339 (e.g. "2026-02-10T00:00:00.000Z")
            due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
            if due_dt < now:
                overdue.append(t)
        except (ValueError, TypeError):
            continue

    return overdue


def get_due_soon_tasks(tasks: list[dict], days: int = 2) -> list[dict]:
    """Filter tasks due within the next N days (excludes overdue)."""
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days)
    due_soon = []

    for t in tasks:
        due = t.get("due")
        if not due:
            continue
        try:
            due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
            if now <= due_dt <= cutoff:
                due_soon.append(t)
        except (ValueError, TypeError):
            continue

    return due_soon


def format_tasks_for_prompt(overdue: list[dict], due_soon: list[dict]) -> str:
    """Format overdue and due-soon tasks as a text block for the LLM prompt."""
    if not overdue and not due_soon:
        return ""

    lines = []

    if overdue:
        lines.append("OVERDUE:")
        for t in overdue:
            due = t.get("due", "")[:10]
            list_name = t.get("list_title", "")
            notes = t.get("notes", "")
            line = f"- {t['title']} (due {due}, list: {list_name})"
            if notes:
                line += f" Notes: {notes[:200]}"
            lines.append(line)

    if due_soon:
        lines.append("DUE SOON:")
        for t in due_soon:
            due = t.get("due", "")[:10]
            list_name = t.get("list_title", "")
            notes = t.get("notes", "")
            line = f"- {t['title']} (due {due}, list: {list_name})"
            if notes:
                line += f" Notes: {notes[:200]}"
            lines.append(line)

    return "\n".join(lines)
