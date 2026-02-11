"""Tests for tasks_fetcher module."""

import unittest
from datetime import datetime, timezone, timedelta

from src.tasks_fetcher import get_overdue_tasks, get_due_soon_tasks, format_tasks_for_prompt


class TestGetOverdueTasks(unittest.TestCase):
    def _make_task(self, title, due_iso):
        return {
            "id": "t1",
            "title": title,
            "notes": "",
            "status": "needsAction",
            "due": due_iso,
            "list_title": "My Tasks",
        }

    def test_identifies_overdue(self):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000Z")
        tasks = [self._make_task("Overdue task", yesterday)]
        result = get_overdue_tasks(tasks)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Overdue task")

    def test_future_task_not_overdue(self):
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000Z")
        tasks = [self._make_task("Future task", tomorrow)]
        result = get_overdue_tasks(tasks)
        self.assertEqual(len(result), 0)

    def test_no_due_date_not_overdue(self):
        tasks = [{"id": "t1", "title": "No date", "due": "", "status": "needsAction"}]
        result = get_overdue_tasks(tasks)
        self.assertEqual(len(result), 0)

    def test_empty_list(self):
        self.assertEqual(get_overdue_tasks([]), [])


class TestGetDueSoonTasks(unittest.TestCase):
    def _make_task(self, title, due_iso):
        return {
            "id": "t1",
            "title": title,
            "due": due_iso,
            "status": "needsAction",
            "list_title": "My Tasks",
        }

    def test_due_tomorrow_is_soon(self):
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000Z")
        tasks = [self._make_task("Due tomorrow", tomorrow)]
        result = get_due_soon_tasks(tasks, days=2)
        self.assertEqual(len(result), 1)

    def test_due_next_week_not_soon(self):
        next_week = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT00:00:00.000Z")
        tasks = [self._make_task("Due next week", next_week)]
        result = get_due_soon_tasks(tasks, days=2)
        self.assertEqual(len(result), 0)

    def test_overdue_excluded_from_due_soon(self):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000Z")
        tasks = [self._make_task("Overdue", yesterday)]
        result = get_due_soon_tasks(tasks, days=2)
        self.assertEqual(len(result), 0)


class TestFormatTasksForPrompt(unittest.TestCase):
    def test_overdue_and_due_soon(self):
        overdue = [{"title": "Task A", "due": "2026-02-08T00:00:00.000Z", "list_title": "Work", "notes": ""}]
        due_soon = [{"title": "Task B", "due": "2026-02-11T00:00:00.000Z", "list_title": "Personal", "notes": ""}]
        result = format_tasks_for_prompt(overdue, due_soon)
        self.assertIn("OVERDUE:", result)
        self.assertIn("Task A", result)
        self.assertIn("DUE SOON:", result)
        self.assertIn("Task B", result)

    def test_empty_returns_empty(self):
        result = format_tasks_for_prompt([], [])
        self.assertEqual(result, "")

    def test_notes_included(self):
        overdue = [{"title": "Task C", "due": "2026-02-08T00:00:00.000Z", "list_title": "Work", "notes": "Important context"}]
        result = format_tasks_for_prompt(overdue, [])
        self.assertIn("Important context", result)


if __name__ == "__main__":
    unittest.main()
