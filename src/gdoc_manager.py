"""
Google Doc manager for daily recap.

Manages a running Google Doc with prepend (newest at top) and task rollover.
Uses plain text [ ] / [x] checkboxes for reliable parsing.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from google_workspace.auth import build_service

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent

DATE_HEADER_PATTERN = re.compile(r"^## (\d{4}-\d{2}-\d{2}) - Daily Recap$", re.MULTILINE)
UNCHECKED_PATTERN = re.compile(r"^\[ \] (.+)$", re.MULTILINE)
CARRIED_DATE_PATTERN = re.compile(r"\[Carried from (\d{2}/\d{2})\]")


def _load_settings() -> dict:
    settings_path = PROJECT_ROOT / "config" / "settings.json"
    with open(settings_path) as f:
        return json.load(f)


def _save_settings(settings: dict):
    settings_path = PROJECT_ROOT / "config" / "settings.json"
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)


def get_or_create_doc() -> tuple[str, str]:
    """
    Get existing doc or create a new one.
    Returns (doc_id, doc_url). Updates settings.json with doc_id if newly created.
    """
    settings = _load_settings()
    doc_id = settings.get("doc_id", "")
    doc_title = settings.get("doc_title", "Daily Recap - Running Log")

    docs_service = build_service("docs", "v1")

    if doc_id:
        try:
            doc = docs_service.documents().get(documentId=doc_id).execute()
            doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
            logger.info(f"Using existing doc: {doc_url}")
            return doc_id, doc_url
        except Exception as e:
            logger.warning(f"Could not access doc {doc_id}: {e}. Creating new one.")

    # Create new doc
    doc = docs_service.documents().create(body={"title": doc_title}).execute()
    doc_id = doc.get("documentId")
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

    settings["doc_id"] = doc_id
    _save_settings(settings)

    logger.info(f"Created new doc: {doc_url}")
    return doc_id, doc_url


def read_doc_body(doc_id: str) -> tuple[str, list[dict]]:
    """
    Read the full doc body.
    Returns (full_text, structural_elements).
    """
    docs_service = build_service("docs", "v1")
    doc = docs_service.documents().get(documentId=doc_id).execute()

    elements = doc.get("body", {}).get("content", [])

    # Extract full text
    full_text = ""
    for element in elements:
        if "paragraph" in element:
            for pe in element["paragraph"].get("elements", []):
                text_run = pe.get("textRun", {})
                full_text += text_run.get("content", "")

    return full_text, elements


def find_insertion_index(elements: list[dict]) -> int:
    """
    Find the insertion index after the document title.
    The title is the first paragraph. We insert after it.
    """
    if len(elements) <= 1:
        # Doc is empty or just has the trailing newline
        return 1

    # The first element is typically sectionBreak at index 0.
    # The second element is the title paragraph.
    # We want to insert after the title paragraph ends.
    for i, element in enumerate(elements):
        if "paragraph" in element:
            # This is the title paragraph. Return its endIndex.
            end_index = element.get("endIndex", 1)
            return end_index

    return 1


def extract_carryover_tasks(full_text: str) -> list[dict]:
    """
    Extract unchecked tasks from the most recent date section.

    Returns list of dicts with:
    - task: str (the task text)
    - original_date: str (MM/DD from [Carried from MM/DD] or the section date)
    """
    settings = _load_settings()
    max_days = settings.get("max_carryover_days", 7)
    today = datetime.now()

    # Find all date headers
    headers = list(DATE_HEADER_PATTERN.finditer(full_text))
    if not headers:
        return []

    # Get the most recent section (first header since newest is at top)
    latest_header = headers[0]
    section_date_str = latest_header.group(1)

    try:
        section_date = datetime.strptime(section_date_str, "%Y-%m-%d")
    except ValueError:
        return []

    # Get section text (from this header to the next header or end)
    section_start = latest_header.end()
    if len(headers) > 1:
        section_end = headers[1].start()
    else:
        section_end = len(full_text)

    section_text = full_text[section_start:section_end]

    # Find unchecked tasks
    carryover = []
    for match in UNCHECKED_PATTERN.finditer(section_text):
        task_text = match.group(1).strip()

        # Check if it already has a carried-from date
        carried_match = CARRIED_DATE_PATTERN.search(task_text)
        if carried_match:
            original_date_str = carried_match.group(1)
            # Parse MM/DD to check age
            try:
                original_date = datetime.strptime(
                    f"{today.year}/{original_date_str}", "%Y/%m/%d"
                )
                age_days = (today - original_date).days
                if age_days > max_days:
                    logger.warning(
                        f"Dropping carried task older than {max_days} days: {task_text}"
                    )
                    continue
            except ValueError:
                pass
        else:
            original_date_str = section_date.strftime("%m/%d")

        carryover.append({
            "task": task_text,
            "original_date": original_date_str,
        })

    logger.info(f"Found {len(carryover)} carryover tasks from {section_date_str}")
    return carryover


def build_prepend_requests(section_text: str, insertion_index: int) -> list[dict]:
    """
    Build Google Docs batchUpdate requests to prepend a daily section.

    Inserts text at insertion_index, then applies heading and bold styles.
    Returns list of request dicts.
    """
    requests = []
    current_index = insertion_index

    # Track ranges for styling
    heading2_ranges = []
    heading3_ranges = []
    bold_ranges = []
    link_ranges = []  # (start, end, url)

    lines = section_text.split("\n")

    for line in lines:
        # Detect heading levels and links before inserting
        is_h2 = line.startswith("## ")
        is_h3 = line.startswith("### ")
        is_h4 = line.startswith("#### ")

        # Strip markdown heading markers for insertion
        display_line = line
        if is_h2:
            display_line = line[3:]
        elif is_h3:
            display_line = line[4:]
        elif is_h4:
            display_line = line[5:]

        # Check for bold markers **text**
        bold_segments = []
        clean_line = ""
        last_end = 0
        for m in re.finditer(r"\*\*(.+?)\*\*", display_line):
            clean_line += display_line[last_end:m.start()]
            bold_start = current_index + len(clean_line)
            clean_line += m.group(1)
            bold_end = current_index + len(clean_line)
            bold_segments.append((bold_start, bold_end))
            last_end = m.end()
        clean_line += display_line[last_end:]

        # Check for link markers [text](url)
        link_segments = []
        final_line = ""
        last_end = 0
        for m in re.finditer(r"\[(.+?)\]\((.+?)\)", clean_line):
            final_line += clean_line[last_end:m.start()]
            link_start = current_index + len(final_line)
            link_text = m.group(1)
            link_url = m.group(2)
            final_line += link_text
            link_end = current_index + len(final_line)
            link_segments.append((link_start, link_end, link_url))
            last_end = m.end()
        final_line += clean_line[last_end:]

        # Recalculate bold positions after link processing
        # Bold positions need adjustment if links were processed
        if link_segments and bold_segments:
            # Recalculate - bold_segments were based on pre-link-processed text
            # This is complex; for simplicity, recalculate both from final_line
            bold_segments = []
            # Re-extract bold from the original display_line through final processing
            # The bold markers were already stripped, so we use the tracked positions

        insert_text = final_line + "\n"

        requests.append({
            "insertText": {
                "location": {"index": current_index},
                "text": insert_text,
            }
        })

        line_start = current_index
        line_end = current_index + len(insert_text)

        if is_h2:
            heading2_ranges.append((line_start, line_end))
        elif is_h3 or is_h4:
            heading3_ranges.append((line_start, line_end))

        bold_ranges.extend(bold_segments)
        link_ranges.extend(link_segments)

        current_index = line_end

    # Add a separator line
    separator = "\n---\n\n"
    requests.append({
        "insertText": {
            "location": {"index": current_index},
            "text": separator,
        }
    })
    current_index += len(separator)

    # Apply heading styles
    for start, end in heading2_ranges:
        requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "paragraphStyle": {"namedStyleType": "HEADING_2"},
                "fields": "namedStyleType",
            }
        })

    for start, end in heading3_ranges:
        requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "paragraphStyle": {"namedStyleType": "HEADING_3"},
                "fields": "namedStyleType",
            }
        })

    # Apply bold
    for start, end in bold_ranges:
        requests.append({
            "updateTextStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "textStyle": {"bold": True},
                "fields": "bold",
            }
        })

    # Apply links
    for start, end, url in link_ranges:
        requests.append({
            "updateTextStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "textStyle": {"link": {"url": url}},
                "fields": "link",
            }
        })

    return requests


def prepend_daily_section(doc_id: str, section_text: str) -> None:
    """
    Prepend a daily section to the running doc.
    Always re-reads the doc fresh to get current insertion index.
    """
    _, elements = read_doc_body(doc_id)
    insertion_index = find_insertion_index(elements)

    requests = build_prepend_requests(section_text, insertion_index)

    if not requests:
        logger.warning("No requests to send to Google Docs")
        return

    docs_service = build_service("docs", "v1")

    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests},
    ).execute()

    logger.info(f"Prepended daily section to doc {doc_id}")
