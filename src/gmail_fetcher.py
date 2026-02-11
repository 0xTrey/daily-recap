"""
Gmail fetcher for daily recap.

Fetches ALL inbox threads (not domain-filtered) and classifies reply status.
Uses google-workspace for auth and includes vendored MIME parsing functions.
"""

import base64
import logging
import re
from datetime import datetime
from email.utils import parseaddr
from pathlib import Path

from google_workspace.auth import build_service

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Vendored from weekly-report/src/gmail_client.py
# Copied here to remove the fragile sys.path.insert dependency.
# ---------------------------------------------------------------------------

def _clean_body_text(text: str) -> str:
    """Strip email noise: quoted replies, signatures, legal disclaimers."""
    lines = text.split("\n")
    cleaned = []

    for line in lines:
        stripped = line.strip()
        if stripped in ("-- ", "--") or stripped.startswith(
            ("Sent from my", "CONFIDENTIAL", "This email and any")
        ):
            break
        if stripped.startswith(">"):
            continue
        cleaned.append(line)

    result = "\n".join(cleaned).strip()
    result = re.sub(r"\n{3,}", "\n\n", result)

    if len(result) > 2000:
        result = result[:2000]

    return result


def extract_body_text(payload: dict) -> str:
    """Extract plain text body from email payload. Handles multipart recursively."""
    body_text = ""

    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {})
    parts = payload.get("parts", [])

    if mime_type == "text/plain" and body.get("data"):
        body_text = base64.urlsafe_b64decode(body["data"]).decode(
            "utf-8", errors="ignore"
        )
    elif parts:
        for part in parts:
            part_mime = part.get("mimeType", "")
            if part_mime == "text/plain":
                part_body = part.get("body", {})
                if part_body.get("data"):
                    body_text = base64.urlsafe_b64decode(part_body["data"]).decode(
                        "utf-8", errors="ignore"
                    )
                    break
            elif part_mime.startswith("multipart/"):
                body_text = extract_body_text(part)
                if body_text:
                    break

    body_text = body_text.strip()
    body_text = _clean_body_text(body_text)
    return body_text


def format_thread_for_llm(thread: dict) -> str:
    """Format a thread for LLM consumption. Labels messages YOU/THEY."""
    lines = [f"Subject: {thread['subject']}", ""]

    messages = thread["messages"]

    if len(messages) > 4:
        kept = [messages[0]] + messages[-2:]
        omitted = len(messages) - 3
    else:
        kept = messages
        omitted = 0

    for i, msg in enumerate(kept):
        if omitted and i == 1:
            lines.append(f"[... {omitted} earlier messages omitted ...]")
            lines.append("")
        label = "YOU wrote:" if msg["is_you"] else "THEY wrote:"
        lines.append(f"--- {label} ({msg['timestamp']}) ---")
        lines.append(msg["body"])
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gmail fetching logic
# ---------------------------------------------------------------------------

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
    service = build_service("gmail", "v1")
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

    user_messages = [m for m in thread["messages"] if m["is_you"]]
    has_user_reply = len(user_messages) > 0

    if has_user_reply:
        thread["status"] = "replied"
        thread["latest_reply_body"] = user_messages[-1]["body"]
    elif has_unread:
        thread["status"] = "unread"
    else:
        thread["status"] = "read_no_reply"

    first_msg_id = thread["messages"][0]["message_id"] if thread["messages"] else ""
    thread["gmail_link"] = f"https://mail.google.com/mail/u/0/#inbox/{first_msg_id}"

    return thread


def fetch_and_classify(start: datetime, end: datetime) -> list[dict]:
    """Fetch inbox threads and classify each one."""
    service = build_service("gmail", "v1")
    user_email = _get_user_email(service)

    threads = fetch_inbox_threads(start, end)
    return [classify_thread(t, user_email) for t in threads]
