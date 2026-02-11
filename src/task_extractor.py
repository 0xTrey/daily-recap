"""
Task extractor for daily recap.

Uses LLM to extract tasks from email, calendar, Granola, Slack, and Google Tasks data.
Deduplicates with rapidfuzz, prioritizes, and formats for Google Doc output.
"""

import logging
from datetime import datetime

from rapidfuzz import fuzz

from src.gmail_fetcher import format_thread_for_llm
from src.llm_client import call_llm, call_llm_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a task extraction assistant for a sales professional at Folloze (a B2B marketing platform company).

Extract every actionable task from the provided data sources. A task is anything that requires follow-up action.

Categorize each task as:
- "luke": Requests from the user's manager (Luke). These are highest priority.
- "internal": Tasks involving Folloze colleagues, internal processes, HR, IT, training.
- "external": Tasks involving prospects, customers, partners, or anyone outside Folloze.

For each task, identify:
- The specific action needed
- The source (email, calendar, granola, slack, google_tasks)
- A brief source detail (e.g., email subject, meeting title, channel name, task list name)
- Any source links (Gmail links, Calendar links, Granola URLs, Slack permalinks)
- Due date if mentioned (ISO format YYYY-MM-DD), or null
- Deal/company name if applicable, or null

Return ONLY a JSON array of task objects. No explanation or markdown."""

TASK_SCHEMA_EXAMPLE = """
Example output format:
[
  {
    "task": "Send revised SOW to Acme Corp",
    "category": "external",
    "source": "email",
    "source_detail": "Subject: Acme SOW Review",
    "source_links": ["https://mail.google.com/mail/u/0/#inbox/abc123"],
    "due_date": "2026-02-07",
    "deal_name": "Acme Corp",
    "status": "open"
  },
  {
    "task": "Get pipeline numbers to Luke by EOD",
    "category": "luke",
    "source": "slack",
    "source_detail": "DM with Luke",
    "source_links": ["https://folloze.slack.com/archives/D0987654/p1738764000000000"],
    "due_date": null,
    "deal_name": null,
    "status": "open"
  }
]"""

WHAT_I_DID_PROMPT = """You are summarizing a sales professional's daily activity at Folloze.

Given the data below, write 3-8 bullet points summarizing what the user DID today (completed actions, meetings attended, emails sent/replied to). Each bullet should be concise (one line) and include the source in parentheses.

Focus on:
- Meetings attended (from calendar and granola)
- Emails replied to (from email data marked as "replied")
- Messages sent in Slack (where is_you=true)
- Completed follow-ups

Return ONLY the bullet points, one per line, starting with "- ". No headers or explanation."""

WAITING_ON_PROMPT = """You are identifying items a sales professional is waiting on.

Given the data below, identify 0-5 items the user is waiting for from others (pending approvals, expected replies, deliverables from colleagues/customers).

Each item should be one line: "- Description (expected DATE if known)"

Return ONLY the bullet points, one per line, starting with "- ". If nothing is pending, return "None"."""


def build_extraction_prompt(
    emails: list[dict],
    events: list[dict],
    granola: dict,
    slack: dict,
    manager_names: list[str],
    google_tasks: str = "",
) -> str:
    """Build the user prompt with all data sources for task extraction."""
    parts = []

    parts.append(f"Manager name(s): {', '.join(manager_names)}")
    parts.append(f"Today's date: {datetime.now().strftime('%Y-%m-%d')}")
    parts.append("")

    # Emails
    if emails:
        parts.append("=== EMAIL THREADS ===")
        for thread in emails:
            status = thread.get("status", "unknown")
            link = thread.get("gmail_link", "")
            parts.append(f"\nThread: {thread['subject']} [Status: {status}] [Link: {link}]")
            parts.append(format_thread_for_llm(thread))
        parts.append("")

    # Calendar events
    if events:
        parts.append("=== CALENDAR EVENTS ===")
        for event in events:
            internal_tag = " [INTERNAL]" if event.get("is_internal") else ""
            link = event.get("html_link", "")
            parts.append(
                f"- {event['start_time']}: {event['title']}{internal_tag} "
                f"| Attendees: {', '.join(event.get('attendees', []))} "
                f"[Link: {link}]"
            )
        parts.append("")

    # Granola meetings
    if granola and granola.get("meetings"):
        parts.append("=== GRANOLA MEETING NOTES ===")
        for meeting in granola["meetings"]:
            url = meeting.get("notes_url", "")
            parts.append(f"\nMeeting: {meeting['title']} ({meeting.get('date', '')}) [Link: {url}]")
            attendees = meeting.get("attendees", [])
            if attendees:
                # Handle both string and dict attendee formats
                attendee_strs = []
                for a in attendees:
                    if isinstance(a, str):
                        attendee_strs.append(a)
                    elif isinstance(a, dict):
                        name = a.get("name", "")
                        email = a.get("email", "")
                        attendee_strs.append(f"{name} <{email}>" if name else email)
                parts.append(f"Attendees: {', '.join(attendee_strs)}")
            parts.append(f"Summary: {meeting.get('summary', '')}")
            if meeting.get("action_items"):
                parts.append("Action items from notes:")
                for item in meeting["action_items"]:
                    parts.append(f"  - {item}")
            if meeting.get("raw_notes"):
                parts.append(f"Full notes: {meeting['raw_notes'][:2000]}")
        parts.append("")

    # Slack messages
    if slack and slack.get("messages"):
        parts.append("=== SLACK MESSAGES ===")
        for msg in slack["messages"]:
            who = "YOU" if msg.get("is_you") else msg.get("sender", "Unknown")
            link = msg.get("permalink", "")
            parts.append(
                f"- [{msg.get('channel', '')}] {who}: {msg.get('text', '')} "
                f"({msg.get('timestamp', '')}) [Link: {link}]"
            )
        parts.append("")

    # Google Tasks
    if google_tasks:
        parts.append("=== GOOGLE TASKS ===")
        parts.append(google_tasks)
        parts.append("")

    parts.append(TASK_SCHEMA_EXAMPLE)

    return "\n".join(parts)


def build_activity_prompt(
    emails: list[dict],
    events: list[dict],
    granola: dict,
    slack: dict,
) -> str:
    """Build prompt for 'What I Did Today' section."""
    parts = []

    if events:
        parts.append("=== CALENDAR (meetings attended) ===")
        for event in events:
            parts.append(f"- {event['start_time']}: {event['title']}")

    if emails:
        parts.append("=== EMAILS ===")
        for thread in emails:
            status = thread.get("status", "unknown")
            parts.append(f"- [{status}] {thread['subject']} ({thread.get('message_count', 0)} messages)")

    if granola and granola.get("meetings"):
        parts.append("=== GRANOLA NOTES ===")
        for meeting in granola["meetings"]:
            parts.append(f"- {meeting['title']}: {meeting.get('summary', '')[:200]}")

    if slack and slack.get("messages"):
        parts.append("=== SLACK (your messages) ===")
        for msg in slack["messages"]:
            if msg.get("is_you"):
                parts.append(f"- [{msg.get('channel', '')}] {msg.get('text', '')[:200]}")

    return "\n".join(parts)


def build_waiting_prompt(
    emails: list[dict],
    events: list[dict],
    granola: dict,
    slack: dict,
) -> str:
    """Build prompt for 'Waiting On' section."""
    return build_activity_prompt(emails, events, granola, slack)


def extract_tasks(
    emails: list[dict],
    events: list[dict],
    granola: dict,
    slack: dict,
    manager_names: list[str],
    google_tasks: str = "",
) -> list[dict]:
    """Extract tasks from all data sources via LLM."""
    prompt = build_extraction_prompt(emails, events, granola, slack, manager_names, google_tasks)
    tasks = call_llm_json(SYSTEM_PROMPT, prompt)

    # Validate and normalize
    valid_tasks = []
    for t in tasks:
        if not isinstance(t, dict) or not t.get("task"):
            continue
        t.setdefault("category", "external")
        t.setdefault("source", "unknown")
        t.setdefault("source_detail", "")
        t.setdefault("source_links", [])
        t.setdefault("due_date", None)
        t.setdefault("deal_name", None)
        t.setdefault("status", "open")
        # Normalize category
        if t["category"] not in ("luke", "internal", "external"):
            t["category"] = "external"
        valid_tasks.append(t)

    logger.info(f"Extracted {len(valid_tasks)} tasks from LLM")
    return valid_tasks


def extract_activity(
    emails: list[dict],
    events: list[dict],
    granola: dict,
    slack: dict,
) -> str:
    """Extract 'What I Did Today' bullets via LLM."""
    prompt = build_activity_prompt(emails, events, granola, slack)
    return call_llm(WHAT_I_DID_PROMPT, prompt, temperature=0.2, max_tokens=8192)


def extract_waiting_on(
    emails: list[dict],
    events: list[dict],
    granola: dict,
    slack: dict,
) -> str:
    """Extract 'Waiting On' items via LLM."""
    prompt = build_waiting_prompt(emails, events, granola, slack)
    return call_llm(WAITING_ON_PROMPT, prompt, temperature=0.2, max_tokens=8192)


def deduplicate_tasks(tasks: list[dict]) -> list[dict]:
    """
    Deduplicate tasks using fuzzy matching.
    Threshold 85: above = merge (keep version with more source links), below = keep both.
    """
    if not tasks:
        return []

    deduped = []
    for task in tasks:
        is_dup = False
        for i, existing in enumerate(deduped):
            score = fuzz.token_sort_ratio(task["task"], existing["task"])
            if score >= 85:
                # Merge: keep the one with more source links
                if len(task.get("source_links", [])) > len(existing.get("source_links", [])):
                    merged_links = list(set(task["source_links"] + existing.get("source_links", [])))
                    task["source_links"] = merged_links
                    deduped[i] = task
                else:
                    merged_links = list(set(existing.get("source_links", []) + task.get("source_links", [])))
                    deduped[i]["source_links"] = merged_links
                is_dup = True
                break
        if not is_dup:
            deduped.append(task)

    if len(deduped) < len(tasks):
        logger.info(f"Deduplication: {len(tasks)} -> {len(deduped)} tasks")

    return deduped


def _sort_key(task: dict) -> tuple:
    """
    Sort key for task prioritization.
    Order: luke (0) < internal (1) < external (2)
    Within category: has due_date < no due_date
    Within dated: earliest first
    """
    category_order = {"luke": 0, "internal": 1, "external": 2}
    cat = category_order.get(task.get("category", "external"), 2)

    due = task.get("due_date")
    if due:
        has_due = 0
        due_sort = due
    else:
        has_due = 1
        due_sort = "9999-99-99"

    urgency = 1
    task_lower = task.get("task", "").lower()
    if any(kw in task_lower for kw in ("today", "asap", "eod", "urgent", "immediately")):
        urgency = 0
    elif any(kw in task_lower for kw in ("contract", "$", "deal", "proposal", "sow")):
        urgency = 0

    return (cat, has_due, due_sort, urgency)


def format_tasks_for_doc(
    tasks: list[dict],
    carryover: list[dict],
    activity_text: str,
    waiting_text: str,
    today: datetime,
    companies_text: str = "",
    overdue_safety_net: list[dict] | None = None,
) -> str:
    """
    Format all extracted data into the daily section markdown for the Google Doc.

    Output format:
    ## YYYY-MM-DD - Daily Recap
    ### What I Did Today
    ### What Needs Doing
    #### Luke Requests
    #### Internal
    #### External
    ### Waiting On
    ### Companies Engaged
    ### Carried Forward
    """
    date_str = today.strftime("%Y-%m-%d")
    lines = []

    lines.append(f"## {date_str} - Daily Recap")
    lines.append("")

    # What I Did Today
    lines.append("### What I Did Today")
    if activity_text and activity_text.strip():
        for line in activity_text.strip().split("\n"):
            line = line.strip()
            if line:
                lines.append(line)
    else:
        lines.append("- No activity data available")
    lines.append("")

    # What Needs Doing
    lines.append("### What Needs Doing")
    lines.append("")

    sorted_tasks = sorted(tasks, key=_sort_key)

    luke_tasks = [t for t in sorted_tasks if t["category"] == "luke"]
    internal_tasks = [t for t in sorted_tasks if t["category"] == "internal"]
    external_tasks = [t for t in sorted_tasks if t["category"] == "external"]

    def format_task_line(task: dict) -> str:
        parts = [f"[ ] {task['task']}"]
        if task.get("due_date"):
            parts[0] += f" (by {task['due_date']})"
        if task.get("deal_name"):
            parts[0] += f" - {task['deal_name']}"
        source = task.get("source", "")
        if source:
            parts[0] += f" ({source})"
        return parts[0]

    if luke_tasks:
        lines.append("#### Luke Requests")
        for t in luke_tasks:
            lines.append(format_task_line(t))
        lines.append("")

    if internal_tasks:
        lines.append("#### Internal")
        for t in internal_tasks:
            lines.append(format_task_line(t))
        lines.append("")

    if external_tasks:
        lines.append("#### External")
        for t in external_tasks:
            lines.append(format_task_line(t))
        lines.append("")

    if not luke_tasks and not internal_tasks and not external_tasks:
        lines.append("No tasks extracted.")
        lines.append("")

    # Safety net: overdue Google Tasks the LLM may have missed
    if overdue_safety_net:
        # Check which overdue tasks are already covered by LLM-extracted tasks
        extracted_titles = {t["task"].lower() for t in tasks}
        uncovered = []
        for ot in overdue_safety_net:
            title_lower = ot.get("title", "").lower()
            # Simple check: if no extracted task contains this title
            if not any(title_lower in et for et in extracted_titles):
                uncovered.append(ot)

        if uncovered:
            lines.append("#### Overdue (Google Tasks)")
            for ot in uncovered:
                due = ot.get("due", "")[:10]
                list_name = ot.get("list_title", "")
                lines.append(f"[ ] {ot['title']} (by {due}) - {list_name} (google_tasks, overdue)")
            lines.append("")

    # Waiting On
    lines.append("### Waiting On")
    if waiting_text and waiting_text.strip() and waiting_text.strip().lower() != "none":
        for line in waiting_text.strip().split("\n"):
            line = line.strip()
            if line:
                lines.append(line)
    else:
        lines.append("- Nothing pending")
    lines.append("")

    # Companies Engaged
    if companies_text:
        lines.append("### Companies Engaged")
        lines.append(companies_text)
        lines.append("")

    # Carried Forward
    if carryover:
        lines.append("### Carried Forward")
        for item in carryover:
            carried_date = item["original_date"]
            task_text = item["task"]
            if f"[Carried from {carried_date}]" not in task_text:
                lines.append(f"[ ] [Carried from {carried_date}] {task_text}")
            else:
                lines.append(f"[ ] {task_text}")
        lines.append("")

    return "\n".join(lines)
