"""Tests for gdoc_manager module."""

import unittest
from datetime import datetime

from src.gdoc_manager import (
    extract_carryover_tasks,
    find_insertion_index,
    build_prepend_requests,
)


class TestExtractCarryoverTasks(unittest.TestCase):
    def test_extracts_unchecked_tasks(self):
        full_text = """Daily Recap - Running Log

## 2026-02-04 - Daily Recap

### What Needs Doing

#### External
[ ] Send SOW to Acme (email)
[x] Call Beta Inc (email)
[ ] Follow up with Gamma (slack)

---

## 2026-02-03 - Daily Recap
[ ] Old task from yesterday
"""
        tasks = extract_carryover_tasks(full_text)
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["task"], "Send SOW to Acme (email)")
        self.assertEqual(tasks[0]["original_date"], "02/04")
        self.assertEqual(tasks[1]["task"], "Follow up with Gamma (slack)")

    def test_preserves_carried_from_date(self):
        # Use yesterday's date so the carried task is within the 7-day window
        from datetime import timedelta
        yesterday = datetime.now() - timedelta(days=1)
        recap_date = yesterday.strftime("%Y-%m-%d")
        recap_mm_dd = yesterday.strftime("%m/%d")
        two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%m/%d")
        full_text = f"""## {recap_date} - Daily Recap

### Carried Forward
[ ] [Carried from {two_days_ago}] Prepare board deck (email)
[ ] New task today (slack)
"""
        tasks = extract_carryover_tasks(full_text)
        self.assertEqual(len(tasks), 2)
        # The carried-from task keeps its original date
        carried = [t for t in tasks if "board deck" in t["task"]]
        self.assertEqual(len(carried), 1)
        self.assertEqual(carried[0]["original_date"], two_days_ago)

    def test_empty_doc(self):
        tasks = extract_carryover_tasks("")
        self.assertEqual(tasks, [])

    def test_no_unchecked_tasks(self):
        full_text = """## 2026-02-04 - Daily Recap

### What Needs Doing
[x] All done (email)
[x] This too (slack)
"""
        tasks = extract_carryover_tasks(full_text)
        self.assertEqual(len(tasks), 0)


class TestFindInsertionIndex(unittest.TestCase):
    def test_empty_doc(self):
        elements = [{"sectionBreak": {}, "startIndex": 0, "endIndex": 1}]
        idx = find_insertion_index(elements)
        self.assertEqual(idx, 1)

    def test_doc_with_title(self):
        elements = [
            {"sectionBreak": {}, "startIndex": 0, "endIndex": 1},
            {
                "paragraph": {
                    "elements": [{"textRun": {"content": "Daily Recap - Running Log\n"}}]
                },
                "startIndex": 1,
                "endIndex": 27,
            },
        ]
        idx = find_insertion_index(elements)
        self.assertEqual(idx, 27)


class TestBuildPrependRequests(unittest.TestCase):
    def test_creates_insert_requests(self):
        section = "## 2026-02-05 - Daily Recap\n### What I Did Today\n- Met with Acme (calendar)\n"
        requests = build_prepend_requests(section, 27)
        # Should have insertText requests
        insert_requests = [r for r in requests if "insertText" in r]
        self.assertTrue(len(insert_requests) > 0)

    def test_applies_heading_styles(self):
        section = "## 2026-02-05 - Daily Recap\n### What I Did Today\n"
        requests = build_prepend_requests(section, 1)
        heading_requests = [r for r in requests if "updateParagraphStyle" in r]
        self.assertTrue(len(heading_requests) >= 2)

        # Check that HEADING_2 is applied
        h2 = [r for r in heading_requests if r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == "HEADING_2"]
        self.assertTrue(len(h2) >= 1)

        # Check that HEADING_3 is applied
        h3 = [r for r in heading_requests if r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == "HEADING_3"]
        self.assertTrue(len(h3) >= 1)


if __name__ == "__main__":
    unittest.main()
