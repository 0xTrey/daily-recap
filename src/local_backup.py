"""
Local backup for daily recap.

Saves daily data as JSON and markdown to ~/.openclaw/daily-sync/ for
historical analysis and recovery.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_BACKUP_DIR = "~/.openclaw/daily-sync"


def save_daily_backup(
    data: dict,
    doc_content: str,
    date: datetime,
    backup_dir: str = DEFAULT_BACKUP_DIR,
) -> Path:
    """Save daily recap data as local JSON and markdown backup.

    Args:
        data: The raw data dict (emails, events, tasks, granola, slack, etc.)
        doc_content: The formatted markdown content written to the Google Doc.
        date: The date being recapped.
        backup_dir: Directory to save backups. Created if it doesn't exist.

    Returns:
        Path to the backup directory.
    """
    backup_path = Path(backup_dir).expanduser()
    backup_path.mkdir(parents=True, exist_ok=True)

    date_str = date.strftime("%Y-%m-%d")

    # Save JSON data
    json_path = backup_path / f"{date_str}.json"
    try:
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"Saved JSON backup: {json_path}")
    except Exception as e:
        logger.warning(f"Failed to save JSON backup: {e}")

    # Save markdown content
    md_path = backup_path / f"{date_str}.md"
    try:
        with open(md_path, "w") as f:
            f.write(doc_content)
        logger.info(f"Saved markdown backup: {md_path}")
    except Exception as e:
        logger.warning(f"Failed to save markdown backup: {e}")

    return backup_path
