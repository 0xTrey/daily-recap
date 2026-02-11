"""
Calendar fetcher for daily recap.

Fetches ALL calendar events (no color/internal filtering).
Tags events with is_internal for categorization but keeps everything.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from google_workspace.auth import build_service

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


def _load_settings() -> dict:
    settings_path = PROJECT_ROOT / "config" / "settings.json"
    with open(settings_path) as f:
        return json.load(f)


def _extract_domain(email: str) -> str:
    if "@" in email:
        return email.split("@")[1].lower()
    return ""


def _is_internal_only(attendees: list[dict], internal_domain: str) -> bool:
    if not attendees:
        return True
    for attendee in attendees:
        domain = _extract_domain(attendee.get("email", ""))
        if domain and domain != internal_domain:
            return False
    return True


def fetch_all_events(start: datetime, end: datetime) -> list[dict]:
    """
    Fetch all calendar events in the given time window.

    Returns all events (internal and external) with is_internal tag.
    Skips only all-day events (no dateTime).

    Each event dict has:
    - title, date, start_time, end_time
    - attendees (list of emails)
    - is_internal (bool)
    - external_domains (set)
    - html_link (Calendar permalink)
    - event_id
    """
    settings = _load_settings()
    internal_domain = settings.get("internal_domain", "folloze.com")

    service = build_service("calendar", "v3")

    time_min = start.isoformat() + "Z" if not start.tzinfo else start.isoformat()
    time_max = end.isoformat() + "Z" if not end.tzinfo else end.isoformat()

    events_result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
        maxResults=500,
    ).execute()

    events = events_result.get("items", [])
    results = []

    for event in events:
        event_start = event.get("start", {})

        # Skip all-day events
        if "dateTime" not in event_start:
            continue

        attendees = event.get("attendees", [])
        is_internal = _is_internal_only(attendees, internal_domain)

        external_domains = set()
        for a in attendees:
            domain = _extract_domain(a.get("email", ""))
            if domain and domain != internal_domain:
                external_domains.add(domain)

        start_time = event_start.get("dateTime", "")
        meeting_date = start_time[:10] if start_time else ""

        results.append({
            "title": event.get("summary", "No Title"),
            "date": meeting_date,
            "start_time": start_time,
            "end_time": event.get("end", {}).get("dateTime", ""),
            "attendees": [a.get("email", "") for a in attendees],
            "is_internal": is_internal,
            "external_domains": external_domains,
            "html_link": event.get("htmlLink", ""),
            "event_id": event.get("id", ""),
        })

    logger.info(f"Fetched {len(results)} calendar events ({sum(1 for e in results if not e['is_internal'])} external)")
    return results
