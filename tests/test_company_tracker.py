"""Tests for company_tracker module."""

import unittest

from src.company_tracker import extract_companies, format_companies_for_doc, _extract_domain, _is_ignored


class TestExtractDomain(unittest.TestCase):
    def test_normal_email(self):
        self.assertEqual(_extract_domain("user@acme.com"), "acme.com")

    def test_no_at_sign(self):
        self.assertEqual(_extract_domain("noemail"), "")

    def test_empty_string(self):
        self.assertEqual(_extract_domain(""), "")


class TestIsIgnored(unittest.TestCase):
    def test_personal_domain(self):
        self.assertTrue(_is_ignored("gmail.com", "folloze.com", set()))

    def test_internal_domain(self):
        self.assertTrue(_is_ignored("folloze.com", "folloze.com", set()))

    def test_config_ignored(self):
        self.assertTrue(_is_ignored("spam.com", "folloze.com", {"spam.com"}))

    def test_external_domain(self):
        self.assertFalse(_is_ignored("acme.com", "folloze.com", set()))

    def test_empty_domain(self):
        self.assertTrue(_is_ignored("", "folloze.com", set()))


class TestExtractCompanies(unittest.TestCase):
    def test_from_emails(self):
        emails = [
            {
                "messages": [
                    {"sender_email": "jane@acme.com"},
                    {"sender_email": "bob@acme.com"},
                    {"sender_email": "me@folloze.com"},
                ]
            }
        ]
        result = extract_companies(emails, [], {}, {})
        self.assertEqual(result.get("acme.com"), 2)
        self.assertNotIn("folloze.com", result)

    def test_from_calendar(self):
        events = [
            {"attendees": ["me@folloze.com", "client@example.com", "partner@example.com"]}
        ]
        result = extract_companies([], events, {}, {})
        self.assertEqual(result.get("beta.io"), 2)
        self.assertNotIn("folloze.com", result)

    def test_filters_personal_domains(self):
        emails = [{"messages": [{"sender_email": "friend@example.com"}]}]
        result = extract_companies(emails, [], {}, {})
        self.assertNotIn("gmail.com", result)

    def test_from_granola(self):
        granola = {
            "meetings": [
                {"attendees": [{"name": "Jane", "email": "jane@acme.com"}]}
            ]
        }
        result = extract_companies([], [], granola, {})
        self.assertEqual(result.get("acme.com"), 1)

    def test_sorted_by_count(self):
        emails = [
            {
                "messages": [
                    {"sender_email": "a@example.com"},
                    {"sender_email": "b@example.com"},
                    {"sender_email": "c@example.com"},
                    {"sender_email": "d@example.com"},
                ]
            }
        ]
        result = extract_companies(emails, [], {}, {})
        keys = list(result.keys())
        self.assertEqual(keys[0], "beta.com")

    def test_empty_sources(self):
        result = extract_companies([], [], {}, {})
        self.assertEqual(result, {})


class TestFormatCompaniesForDoc(unittest.TestCase):
    def test_formats_correctly(self):
        companies = {"acme.com": 5, "beta.io": 2}
        result = format_companies_for_doc(companies)
        self.assertIn("acme.com (5 interactions)", result)
        self.assertIn("beta.io (2 interactions)", result)

    def test_empty_returns_empty(self):
        self.assertEqual(format_companies_for_doc({}), "")

    def test_truncates_long_list(self):
        companies = {f"company{i}.com": i for i in range(20)}
        result = format_companies_for_doc(companies, max_shown=5)
        self.assertIn("... and 15 more", result)


if __name__ == "__main__":
    unittest.main()
