"""Tests for task_extractor module."""

import unittest
from datetime import datetime

from src.task_extractor import deduplicate_tasks, format_tasks_for_doc, _sort_key


class TestDeduplicateTasks(unittest.TestCase):
    def test_removes_duplicates(self):
        tasks = [
            {"task": "Send SOW to Acme Corp", "category": "external", "source": "email", "source_links": ["link1"]},
            {"task": "Send the SOW to Acme Corp", "category": "external", "source": "granola", "source_links": ["link2"]},
        ]
        result = deduplicate_tasks(tasks)
        self.assertEqual(len(result), 1)
        # Should merge source links
        self.assertEqual(len(result[0]["source_links"]), 2)

    def test_keeps_distinct_tasks(self):
        tasks = [
            {"task": "Send SOW to Acme Corp", "category": "external", "source": "email", "source_links": []},
            {"task": "Call Beta Inc about pricing", "category": "external", "source": "slack", "source_links": []},
        ]
        result = deduplicate_tasks(tasks)
        self.assertEqual(len(result), 2)

    def test_empty_list(self):
        self.assertEqual(deduplicate_tasks([]), [])

    def test_single_task(self):
        tasks = [{"task": "Do something", "category": "internal", "source": "email", "source_links": []}]
        result = deduplicate_tasks(tasks)
        self.assertEqual(len(result), 1)


class TestSortKey(unittest.TestCase):
    def test_luke_before_internal(self):
        luke = {"task": "Get numbers", "category": "luke", "due_date": None}
        internal = {"task": "Training", "category": "internal", "due_date": None}
        self.assertLess(_sort_key(luke), _sort_key(internal))

    def test_internal_before_external(self):
        internal = {"task": "Training", "category": "internal", "due_date": None}
        external = {"task": "Send SOW", "category": "external", "due_date": None}
        self.assertLess(_sort_key(internal), _sort_key(external))

    def test_dated_before_undated(self):
        dated = {"task": "Do X", "category": "external", "due_date": "2026-02-07"}
        undated = {"task": "Do Y", "category": "external", "due_date": None}
        self.assertLess(_sort_key(dated), _sort_key(undated))

    def test_earlier_date_first(self):
        early = {"task": "Do X", "category": "external", "due_date": "2026-02-06"}
        late = {"task": "Do Y", "category": "external", "due_date": "2026-02-10"}
        self.assertLess(_sort_key(early), _sort_key(late))


class TestFormatTasksForDoc(unittest.TestCase):
    def test_basic_format(self):
        tasks = [
            {
                "task": "Get pipeline numbers to Luke",
                "category": "luke",
                "source": "slack",
                "source_detail": "DM with Luke",
                "source_links": [],
                "due_date": None,
                "deal_name": None,
                "status": "open",
            },
            {
                "task": "Send SOW to Acme",
                "category": "external",
                "source": "email",
                "source_detail": "Subject: Acme SOW",
                "source_links": [],
                "due_date": "2026-02-07",
                "deal_name": "Acme Corp",
                "status": "open",
            },
        ]
        carryover = [{"task": "Prepare board deck", "original_date": "02/03"}]
        today = datetime(2026, 2, 5)

        result = format_tasks_for_doc(
            tasks, carryover,
            activity_text="- Met with Acme (calendar)",
            waiting_text="- Legal review of Beta MSA",
            today=today,
        )

        self.assertIn("## 2026-02-05 - Daily Recap", result)
        self.assertIn("### What I Did Today", result)
        self.assertIn("### What Needs Doing", result)
        self.assertIn("#### Luke Requests", result)
        self.assertIn("#### External", result)
        self.assertIn("[ ] Get pipeline numbers to Luke", result)
        self.assertIn("[ ] Send SOW to Acme", result)
        self.assertIn("### Waiting On", result)
        self.assertIn("### Carried Forward", result)
        self.assertIn("[Carried from 02/03]", result)

    def test_no_tasks(self):
        today = datetime(2026, 2, 5)
        result = format_tasks_for_doc([], [], "- Nothing", "None", today)
        self.assertIn("No tasks extracted", result)

    def test_no_carryover(self):
        today = datetime(2026, 2, 5)
        result = format_tasks_for_doc([], [], "- Did stuff", "None", today)
        self.assertNotIn("Carried Forward", result)


if __name__ == "__main__":
    unittest.main()
