"""
Gmail fetcher for daily recap.

Fetches ALL inbox threads (not domain-filtered) and classifies reply status.
Reuses extract_body_text() from weekly-report for MIME parsing.
"""

import logging
import sys
from datetime import datetime
from email.utils import parseaddr
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Import extract_body_text from weekly-report
sys.path.insert(0, str(Path.home() / "weekly-report" / "src"))
from gmail_client import extract_body_text, format_thread_for_llm  # noqa: E402

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


def _get_credentials() -> Credentials:
    token_path = PROJECT_ROOT / "token.json"
    if not token_path.exists():
        raise FileNotFoundError("token.json not found. Run setup_google_auth.py first.")
    return Credentials.from_authorized_user_file(str(token_path))


def _get_user_email(service) -> str:
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")


def fetch_inbox_threads(start: datetime, end: datetime) -> list[dict]:
    """
    Fetch all inbox threads in the given time window.

    Returns list of thread dicts with:
    - thread_id, subject, messages (list), message_count
    Each message has: sender, sender_email, body, timestamp, is_you, message_id, label_ids
    """
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds)
    user_email = _get_user_email(service)
    user_domain = user_email.split("@")[1] if "@" in user_email else ""

    after_epoch = int(start.timestamp())
    before_epoch = int(end.timestamp())

    query = (
        f"in:inbox after:{after_epoch} before:{before_epoch} "
        f'-subject:(Accepted OR Declined OR "Invitation:" OR "Updated invitation:")'
    )

    logger.info(f"Gmail query: {query}")

    all_message_refs = []
    page_token = None

    while True:
        results = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=200,
            pageToken=page_token,
        ).execute()

        all_message_refs.extend(results.get("messages", []))
        page_token = results.get("nextPageToken")
        if not page_token:
            break

    logger.info(f"Found {len(all_message_refs)} messages in inbox")

    # Group messages by thread
    threads: dict[str, dict] = {}

    for msg_ref in all_message_refs:
        msg_id = msg_ref["id"]
        thread_id = msg_ref.get("threadId", msg_id)

        message = service.users().messages().get(
            userId="me",
            id=msg_id,
            format="full",
        ).execute()

        payload = message.get("payload", {})
        headers = payload.get("headers", [])
        label_ids = message.get("labelIds", [])

        subject = ""
        sender = ""
        date_str = ""

        for header in headers:
            name = header.get("name", "").lower()
            value = header.get("value", "")
            if name == "subject":
                subject = value
            elif name == "from":
                sender = value
            elif name == "date":
                date_str = value

        _, sender_email = parseaddr(sender)
        sender_domain = sender_email.split("@")[1] if "@" in sender_email else ""
        is_you = sender_domain == user_domain

        body = extract_body_text(payload)

        if thread_id not in threads:
            threads[thread_id] = {
                "thread_id": thread_id,
                "subject": subject,
                "messages": [],
                "label_ids": set(),
            }

        threads[thread_id]["messages"].append({
            "sender": sender,
            "sender_email": sender_email,
            "body": body,
            "timestamp": date_str,
            "is_you": is_you,
            "message_id": msg_id,
            "label_ids": label_ids,
        })
        threads[thread_id]["label_ids"].update(label_ids)

    # Sort messages within each thread and convert label_ids set to list
    for thread in threads.values():
        thread["messages"].sort(key=lambda m: m["timestamp"])
        thread["label_ids"] = list(thread["label_ids"])
        thread["message_count"] = len(thread["messages"])

    result = list(threads.values())
    logger.info(f"Grouped into {len(result)} threads")
    return result


def classify_thread(thread: dict, user_email: str) -> dict:
    """
    Classify a thread's reply status.

    Returns the thread dict with added fields:
    - status: "unread" | "read_no_reply" | "replied"
    - latest_reply_body: str (only if replied)
    - gmail_link: str
    """
    has_unread = "UNREAD" in thread.get("label_ids", [])
    user_domain = user_email.split("@")[1] if "@" in user_email else ""

    user_messages = [m for m in thread["messages"] if m["is_you"]]
    has_user_reply = len(user_messages) > 0

    if has_user_reply:
        thread["status"] = "replied"
        thread["latest_reply_body"] = user_messages[-1]["body"]
    elif has_unread:
        thread["status"] = "unread"
    else:
        thread["status"] = "read_no_reply"

    # Build Gmail permalink from first message ID
    first_msg_id = thread["messages"][0]["message_id"] if thread["messages"] else ""
    thread["gmail_link"] = f"https://mail.google.com/mail/u/0/#inbox/{first_msg_id}"

    return thread


def fetch_and_classify(start: datetime, end: datetime) -> list[dict]:
    """Fetch inbox threads and classify each one."""
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds)
    user_email = _get_user_email(service)

    threads = fetch_inbox_threads(start, end)
    return [classify_thread(t, user_email) for t in threads]
