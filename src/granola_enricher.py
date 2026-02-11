"""
Granola data enricher for daily recap.

Merges Stage 1 MCP Granola data (which has notes_url) with richer data from
granola_reader (which has panels, user notes, attendee emails). Falls back
gracefully if granola_reader is unavailable.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _load_daily_digest(target_date: datetime) -> dict | None:
    """Load daily digest from granola_reader, returns None on failure."""
    try:
        from granola_reader import GranolaReader
        gr = GranolaReader()
        date_str = target_date.strftime("%Y-%m-%d")
        digest = gr.get_daily_digest(date=date_str)
        logger.info(
            f"Loaded granola_reader digest: {digest.get('meeting_count', 0)} meetings"
        )
        return digest
    except ImportError:
        logger.warning("granola_reader not installed, skipping enrichment")
        return None
    except FileNotFoundError:
        logger.warning("Granola cache not found, skipping enrichment")
        return None
    except Exception as e:
        logger.warning(f"granola_reader failed: {e}, skipping enrichment")
        return None


def enrich_granola_data(stage1_granola: dict, target_date: datetime) -> dict:
    """Enrich Stage 1 Granola data with granola_reader digest data.

    Merges richer fields (panels/summary, user notes, attendee emails) from
    granola_reader into the Stage 1 data, while preserving notes_url from
    Stage 1 (which granola_reader cannot produce).

    Args:
        stage1_granola: Granola dict from Stage 1 JSON (has meetings with notes_url).
        target_date: The date to load the digest for.

    Returns:
        Enriched granola dict in the same schema as stage1_granola.
    """
    digest = _load_daily_digest(target_date)

    if not digest or not digest.get("meetings"):
        logger.info("No granola_reader data available, using Stage 1 data as-is")
        return stage1_granola

    # Build a lookup from digest meetings by title (best available key)
    digest_by_title = {}
    for m in digest["meetings"]:
        title = m.get("title", "").strip().lower()
        if title:
            digest_by_title[title] = m

    stage1_meetings = stage1_granola.get("meetings", [])
    enriched_meetings = []

    # Track which Stage 1 meetings we've processed
    matched_titles = set()

    for s1_meeting in stage1_meetings:
        title = s1_meeting.get("title", "").strip()
        title_lower = title.lower()

        digest_match = digest_by_title.get(title_lower)

        if digest_match:
            matched_titles.add(title_lower)
            enriched = {
                "title": s1_meeting.get("title", digest_match.get("title", "")),
                "date": s1_meeting.get("date", digest_match.get("date", "")),
                "notes_url": s1_meeting.get("notes_url", ""),
                # Prefer digest data for richer fields
                "summary": digest_match.get("summary", s1_meeting.get("summary", "")),
                "attendees": _merge_attendees(
                    s1_meeting.get("attendees", []),
                    digest_match.get("attendees", []),
                ),
                "action_items": s1_meeting.get("action_items", []),
                "raw_notes": digest_match.get("user_notes", s1_meeting.get("raw_notes", "")),
                "companies": digest_match.get("companies", []),
                "has_transcript": digest_match.get("has_transcript", False),
            }
            enriched_meetings.append(enriched)
        else:
            enriched_meetings.append(s1_meeting)

    # Add any digest meetings not present in Stage 1
    for m in digest["meetings"]:
        title_lower = m.get("title", "").strip().lower()
        if title_lower and title_lower not in matched_titles:
            enriched_meetings.append({
                "title": m.get("title", ""),
                "date": m.get("date", ""),
                "notes_url": "",
                "summary": m.get("summary", ""),
                "attendees": m.get("attendees", []),
                "action_items": [],
                "raw_notes": m.get("user_notes", ""),
                "companies": m.get("companies", []),
                "has_transcript": m.get("has_transcript", False),
            })

    result = dict(stage1_granola)
    result["meetings"] = enriched_meetings
    logger.info(
        f"Enriched Granola data: {len(stage1_meetings)} Stage 1 + "
        f"{len(enriched_meetings) - len(stage1_meetings)} new from reader = "
        f"{len(enriched_meetings)} total meetings"
    )
    return result


def _merge_attendees(stage1_attendees: list, digest_attendees: list) -> list:
    """Merge attendee lists, preferring digest format (has email + name)."""
    # If Stage 1 has simple string attendees and digest has rich dicts, prefer digest
    if digest_attendees and isinstance(digest_attendees[0], dict):
        # Build set of emails from digest
        digest_emails = {a.get("email", "").lower() for a in digest_attendees}

        merged = list(digest_attendees)

        # Add any Stage 1 attendees not in digest
        for a in stage1_attendees:
            if isinstance(a, str):
                if a.lower() not in digest_emails:
                    merged.append(a)
            elif isinstance(a, dict):
                email = a.get("email", "").lower()
                if email not in digest_emails:
                    merged.append(a)

        return merged

    # If digest doesn't have richer data, return Stage 1
    return stage1_attendees if stage1_attendees else digest_attendees
