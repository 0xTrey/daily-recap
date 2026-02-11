"""Tests for task_extractor module."""

import unittest
from datetime import datetime

from src.task_extractor import deduplicate_tasks, format_tasks_for_doc, _sort_key, build_extraction_prompt


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


class TestBuildExtractionPrompt(unittest.TestCase):
    def test_includes_google_tasks_section(self):
        google_tasks = "OVERDUE:\n- Complete review (due 2026-02-08, list: Work)"
        result = build_extraction_prompt([], [], {}, {}, ["Luke"], google_tasks=google_tasks)
        self.assertIn("=== GOOGLE TASKS ===", result)
        self.assertIn("Complete review", result)

    def test_no_google_tasks_when_empty(self):
        result = build_extraction_prompt([], [], {}, {}, ["Luke"], google_tasks="")
        self.assertNotIn("GOOGLE TASKS", result)

    def test_handles_dict_attendees_in_granola(self):
        granola = {
            "meetings": [{
                "title": "Test Meeting",
                "date": "2026-02-10",
                "notes_url": "",
                "summary": "Test",
                "attendees": [{"name": "Jane", "email": "jane@acme.com"}],
                "action_items": [],
            }]
        }
        result = build_extraction_prompt([], [], granola, {}, ["Luke"])
        self.assertIn("Jane <jane@acme.com>", result)


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

    def test_companies_section(self):
        today = datetime(2026, 2, 5)
        result = format_tasks_for_doc(
            [], [], "- Did stuff", "None", today,
            companies_text="- acme.com (5 interactions)\n- beta.io (2 interactions)",
        )
        self.assertIn("### Companies Engaged", result)
        self.assertIn("acme.com (5 interactions)", result)

    def test_no_companies_section_when_empty(self):
        today = datetime(2026, 2, 5)
        result = format_tasks_for_doc([], [], "- Did stuff", "None", today, companies_text="")
        self.assertNotIn("Companies Engaged", result)

    def test_overdue_safety_net(self):
        today = datetime(2026, 2, 5)
        overdue = [
            {"title": "Complete annual review", "due": "2026-02-03T00:00:00.000Z", "list_title": "Work"}
        ]
        result = format_tasks_for_doc(
            [], [], "- Did stuff", "None", today,
            overdue_safety_net=overdue,
        )
        self.assertIn("#### Overdue (Google Tasks)", result)
        self.assertIn("Complete annual review", result)
        self.assertIn("google_tasks, overdue", result)

    def test_overdue_safety_net_skips_covered(self):
        today = datetime(2026, 2, 5)
        tasks = [
            {
                "task": "Complete annual review by Friday",
                "category": "internal",
                "source": "google_tasks",
                "due_date": "2026-02-03",
                "deal_name": None,
                "status": "open",
            }
        ]
        overdue = [
            {"title": "complete annual review", "due": "2026-02-03T00:00:00.000Z", "list_title": "Work"}
        ]
        result = format_tasks_for_doc(
            tasks, [], "- Did stuff", "None", today,
            overdue_safety_net=overdue,
        )
        # The overdue safety net section should NOT appear because the LLM already extracted it
        self.assertNotIn("#### Overdue (Google Tasks)", result)


if __name__ == "__main__":
    unittest.main()
