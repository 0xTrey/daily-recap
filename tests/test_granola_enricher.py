"""Tests for granola_enricher module."""

import unittest
from datetime import datetime
from unittest.mock import patch

from src.granola_enricher import enrich_granola_data, _merge_attendees


class TestMergeAttendees(unittest.TestCase):
    def test_digest_dicts_preferred(self):
        stage1 = ["jane@acme.com", "bob@acme.com"]
        digest = [{"name": "Jane", "email": "jane@acme.com"}, {"name": "Bob", "email": "bob@acme.com"}]
        result = _merge_attendees(stage1, digest)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(isinstance(a, dict) for a in result))

    def test_stage1_extras_added(self):
        stage1 = ["jane@acme.com", "extra@other.com"]
        digest = [{"name": "Jane", "email": "jane@acme.com"}]
        result = _merge_attendees(stage1, digest)
        self.assertEqual(len(result), 2)

    def test_empty_both(self):
        result = _merge_attendees([], [])
        self.assertEqual(result, [])

    def test_stage1_only(self):
        stage1 = ["a@test.com"]
        result = _merge_attendees(stage1, [])
        self.assertEqual(result, ["a@test.com"])


class TestEnrichGranolaData(unittest.TestCase):
    @patch("src.granola_enricher._load_daily_digest")
    def test_enriches_matching_meetings(self, mock_digest):
        mock_digest.return_value = {
            "meetings": [
                {
                    "title": "Acme Demo",
                    "date": "2026-02-10",
                    "summary": "Discussed pricing and next steps",
                    "attendees": [{"name": "Jane", "email": "jane@acme.com"}],
                    "user_notes": "Need to send proposal",
                    "companies": ["acme.com"],
                    "has_transcript": True,
                }
            ]
        }

        stage1 = {
            "meetings": [
                {
                    "title": "Acme Demo",
                    "date": "2026-02-10",
                    "notes_url": "https://granola.ai/notes/abc123",
                    "summary": "Short summary",
                    "attendees": ["jane@acme.com"],
                    "action_items": ["Send proposal"],
                    "raw_notes": "",
                }
            ]
        }

        result = enrich_granola_data(stage1, datetime(2026, 2, 10))
        meetings = result["meetings"]
        self.assertEqual(len(meetings), 1)
        # Should keep notes_url from Stage 1
        self.assertEqual(meetings[0]["notes_url"], "https://granola.ai/notes/abc123")
        # Should use richer summary from digest
        self.assertIn("pricing", meetings[0]["summary"])
        # Should have user notes from digest
        self.assertEqual(meetings[0]["raw_notes"], "Need to send proposal")
        # Should have companies from digest
        self.assertIn("acme.com", meetings[0]["companies"])

    @patch("src.granola_enricher._load_daily_digest")
    def test_adds_digest_only_meetings(self, mock_digest):
        mock_digest.return_value = {
            "meetings": [
                {
                    "title": "Internal Standup",
                    "date": "2026-02-10",
                    "summary": "Quick sync",
                    "attendees": [],
                    "user_notes": "",
                    "companies": [],
                    "has_transcript": False,
                }
            ]
        }
        stage1 = {"meetings": []}
        result = enrich_granola_data(stage1, datetime(2026, 2, 10))
        self.assertEqual(len(result["meetings"]), 1)
        self.assertEqual(result["meetings"][0]["title"], "Internal Standup")

    @patch("src.granola_enricher._load_daily_digest")
    def test_fallback_on_no_digest(self, mock_digest):
        mock_digest.return_value = None
        stage1 = {"meetings": [{"title": "Test", "date": "2026-02-10"}]}
        result = enrich_granola_data(stage1, datetime(2026, 2, 10))
        self.assertEqual(result, stage1)

    @patch("src.granola_enricher._load_daily_digest")
    def test_empty_stage1_uses_digest(self, mock_digest):
        mock_digest.return_value = {
            "meetings": [
                {
                    "title": "Team Meeting",
                    "date": "2026-02-10",
                    "summary": "Recap",
                    "attendees": [],
                    "user_notes": "",
                    "companies": [],
                    "has_transcript": False,
                }
            ]
        }
        result = enrich_granola_data({}, datetime(2026, 2, 10))
        self.assertEqual(len(result["meetings"]), 1)


if __name__ == "__main__":
    unittest.main()
