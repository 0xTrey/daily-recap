"""Tests for calendar_fetcher module."""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

from src.calendar_fetcher import _is_internal_only, _extract_domain


class TestHelpers(unittest.TestCase):
    def test_extract_domain(self):
        self.assertEqual(_extract_domain("user@folloze.com"), "folloze.com")
        self.assertEqual(_extract_domain("user@acme.co"), "acme.co")
        self.assertEqual(_extract_domain("noemail"), "")

    def test_internal_only_all_internal(self):
        attendees = [
            {"email": "alice@folloze.com"},
            {"email": "bob@folloze.com"},
        ]
        self.assertTrue(_is_internal_only(attendees, "folloze.com"))

    def test_internal_only_with_external(self):
        attendees = [
            {"email": "alice@folloze.com"},
            {"email": "jane@acme.com"},
        ]
        self.assertFalse(_is_internal_only(attendees, "folloze.com"))

    def test_internal_only_empty(self):
        self.assertTrue(_is_internal_only([], "folloze.com"))

    def test_internal_only_no_attendees(self):
        self.assertTrue(_is_internal_only([], "folloze.com"))


class TestFetchAllEvents(unittest.TestCase):
    @patch("src.calendar_fetcher.build")
    @patch("src.calendar_fetcher._get_credentials")
    @patch("src.calendar_fetcher._load_settings")
    def test_skips_allday_events(self, mock_settings, mock_creds, mock_build):
        mock_settings.return_value = {"internal_domain": "folloze.com"}
        mock_creds.return_value = MagicMock()

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "summary": "All Day Event",
                    "start": {"date": "2026-02-05"},
                    "end": {"date": "2026-02-06"},
                },
                {
                    "summary": "Real Meeting",
                    "start": {"dateTime": "2026-02-05T10:00:00-06:00"},
                    "end": {"dateTime": "2026-02-05T11:00:00-06:00"},
                    "attendees": [{"email": "me@folloze.com"}],
                    "htmlLink": "https://calendar.google.com/event/123",
                    "id": "evt123",
                },
            ]
        }

        from src.calendar_fetcher import fetch_all_events

        start = datetime(2026, 2, 5, 0, 0)
        end = datetime(2026, 2, 5, 23, 59)
        results = fetch_all_events(start, end)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Real Meeting")
        self.assertTrue(results[0]["is_internal"])
        self.assertEqual(results[0]["html_link"], "https://calendar.google.com/event/123")

    @patch("src.calendar_fetcher.build")
    @patch("src.calendar_fetcher._get_credentials")
    @patch("src.calendar_fetcher._load_settings")
    def test_tags_external_events(self, mock_settings, mock_creds, mock_build):
        mock_settings.return_value = {"internal_domain": "folloze.com"}
        mock_creds.return_value = MagicMock()

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "summary": "External Call",
                    "start": {"dateTime": "2026-02-05T14:00:00-06:00"},
                    "end": {"dateTime": "2026-02-05T15:00:00-06:00"},
                    "attendees": [
                        {"email": "me@folloze.com"},
                        {"email": "client@acme.com"},
                    ],
                    "htmlLink": "https://calendar.google.com/event/456",
                    "id": "evt456",
                },
            ]
        }

        from src.calendar_fetcher import fetch_all_events

        start = datetime(2026, 2, 5, 0, 0)
        end = datetime(2026, 2, 5, 23, 59)
        results = fetch_all_events(start, end)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["is_internal"])
        self.assertIn("acme.com", results[0]["external_domains"])


if __name__ == "__main__":
    unittest.main()
