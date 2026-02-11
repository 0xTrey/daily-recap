"""
Company tracker for daily recap.

Extracts external company domains from all data sources (email, calendar,
Granola, Slack) and counts interactions. Runs post-LLM to avoid inflating
the extraction prompt.
"""

import logging
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

_PERSONAL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "me.com",
    "aol.com",
    "protonmail.com",
    "gmx.com",
    "zoho.com",
}


def _extract_domain(email: str) -> str:
    """Extract domain from an email address."""
    if "@" in email:
        return email.split("@")[1].lower()
    return ""


def _is_ignored(domain: str, internal_domain: str, ignored_domains: set[str]) -> bool:
    """Check if a domain should be excluded from company tracking."""
    if not domain:
        return True
    if domain in ignored_domains:
        return True
    if domain in _PERSONAL_DOMAINS:
        return True
    if internal_domain and internal_domain in domain:
        return True
    return False


def extract_companies(
    emails: list[dict],
    events: list[dict],
    granola: dict,
    slack: dict,
    internal_domain: str = "folloze.com",
    ignored_domains: set[str] | None = None,
) -> dict[str, int]:
    """Extract company domains and interaction counts from all sources.

    Args:
        emails: Classified email threads from gmail_fetcher.
        events: Calendar events from calendar_fetcher.
        granola: Granola data dict with "meetings" key.
        slack: Slack data dict with "messages" key.
        internal_domain: The user's company domain to exclude.
        ignored_domains: Additional domains to exclude.

    Returns:
        Dict of {domain: interaction_count}, sorted by count descending.
    """
    ignored = ignored_domains or set()
    companies: dict[str, int] = defaultdict(int)

    # Email threads: extract domains from sender_email in messages
    for thread in emails:
        for msg in thread.get("messages", []):
            sender_email = msg.get("sender_email", "")
            domain = _extract_domain(sender_email)
            if not _is_ignored(domain, internal_domain, ignored):
                companies[domain] += 1

    # Calendar events: extract from attendees
    for event in events:
        for attendee_email in event.get("attendees", []):
            domain = _extract_domain(attendee_email)
            if not _is_ignored(domain, internal_domain, ignored):
                companies[domain] += 1

    # Granola meetings: extract from attendee emails and external_domains
    if granola:
        for meeting in granola.get("meetings", []):
            for attendee in meeting.get("attendees", []):
                email = attendee if isinstance(attendee, str) else attendee.get("email", "")
                domain = _extract_domain(email)
                if not _is_ignored(domain, internal_domain, ignored):
                    companies[domain] += 1

    # Slack messages: extract domains from email-like patterns in text
    if slack:
        email_pattern = re.compile(r"[\w.\-]+@([\w.\-]+\.\w+)")
        for msg in slack.get("messages", []):
            text = msg.get("text", "")
            for match in email_pattern.finditer(text):
                domain = match.group(1).lower()
                if not _is_ignored(domain, internal_domain, ignored):
                    companies[domain] += 1

    # Sort by count descending
    return dict(sorted(companies.items(), key=lambda x: x[1], reverse=True))


def format_companies_for_doc(companies: dict[str, int], max_shown: int = 15) -> str:
    """Format companies section for the Google Doc output.

    Args:
        companies: Dict of {domain: count} from extract_companies.
        max_shown: Max companies to display.

    Returns:
        Markdown text block for the doc section.
    """
    if not companies:
        return ""

    lines = []
    shown = list(companies.items())[:max_shown]
    for domain, count in shown:
        lines.append(f"- {domain} ({count} interactions)")

    if len(companies) > max_shown:
        lines.append(f"- ... and {len(companies) - max_shown} more")

    return "\n".join(lines)
