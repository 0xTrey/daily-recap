"""Tests for gmail_fetcher module."""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

from src.gmail_fetcher import classify_thread


class TestClassifyThread(unittest.TestCase):
    def _make_thread(self, label_ids=None, messages=None):
        return {
            "thread_id": "t1",
            "subject": "Test Subject",
            "label_ids": label_ids or [],
            "messages": messages or [],
            "message_count": len(messages or []),
        }

    def _make_message(self, is_you=False, body="Hello", msg_id="m1"):
        return {
            "sender": "test@example.com",
            "sender_email": "test@example.com",
            "body": body,
            "timestamp": "2026-02-05T10:00:00",
            "is_you": is_you,
            "message_id": msg_id,
            "label_ids": [],
        }

    def test_unread_thread(self):
        thread = self._make_thread(
            label_ids=["INBOX", "UNREAD"],
            messages=[self._make_message(is_you=False)],
        )
        result = classify_thread(thread, "me@folloze.com")
        self.assertEqual(result["status"], "unread")

    def test_read_no_reply(self):
        thread = self._make_thread(
            label_ids=["INBOX"],
            messages=[self._make_message(is_you=False)],
        )
        result = classify_thread(thread, "me@folloze.com")
        self.assertEqual(result["status"], "read_no_reply")

    def test_replied(self):
        thread = self._make_thread(
            label_ids=["INBOX"],
            messages=[
                self._make_message(is_you=False, msg_id="m1"),
                self._make_message(is_you=True, body="My reply", msg_id="m2"),
            ],
        )
        result = classify_thread(thread, "me@folloze.com")
        self.assertEqual(result["status"], "replied")
        self.assertEqual(result["latest_reply_body"], "My reply")

    def test_gmail_link_constructed(self):
        thread = self._make_thread(
            label_ids=["INBOX"],
            messages=[self._make_message(msg_id="abc123")],
        )
        result = classify_thread(thread, "me@folloze.com")
        self.assertEqual(result["gmail_link"], "https://mail.google.com/mail/u/0/#inbox/abc123")


if __name__ == "__main__":
    unittest.main()
