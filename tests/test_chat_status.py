"""Tests for Qualtrics compute_chat_status (ended group, never joined)."""

import unittest
from datetime import datetime, timedelta

from session_runtime import compute_chat_status


class _Session:
    group_chat_duration_minutes = 5


class TestComputeChatStatus(unittest.TestCase):
    def test_never_joined_without_group_id(self):
        out = compute_chat_status(
            _Session(),
            {},
            "p1",
            {"group_id": None, "messages": [], "display_name": "Alice"},
            "export",
        )
        self.assertEqual(out["chat_status"], "never_joined")

    def test_ended_group_empty_group_info_duration_limit_with_messages(self):
        """After end_group, group_info is {}; must not return never_joined."""
        out = compute_chat_status(
            _Session(),
            {},
            "p1",
            {
                "group_id": "GRP-TEST",
                "messages": [{"sender": "Alice", "text": "hello"}],
                "display_name": "Alice",
            },
            "duration_limit",
        )
        self.assertEqual(out["chat_status"], "completed_full")
        self.assertIn("completed", out["chat_status_detail"].lower())

    def test_ended_group_empty_group_info_duration_limit_no_messages(self):
        out = compute_chat_status(
            _Session(),
            None,
            "p1",
            {"group_id": "GRP-TEST", "messages": [], "display_name": "Alice"},
            "session_ended",
        )
        self.assertEqual(out["chat_status"], "completed_full")
        self.assertIn("no messages", out["chat_status_detail"].lower())

    def test_ended_group_empty_group_info_early_leave_with_messages(self):
        out = compute_chat_status(
            _Session(),
            {},
            "p1",
            {
                "group_id": "GRP-TEST",
                "messages": [{"sender": "Alice", "text": "bye"}],
                "display_name": "Alice",
            },
            "page_unload",
        )
        self.assertEqual(out["chat_status"], "left_early")

    def test_ended_group_empty_group_info_post_chat_handoff_defaults_completed(self):
        out = compute_chat_status(
            _Session(),
            {},
            "p1",
            {
                "group_id": "GRP-TEST",
                "messages": [{"sender": "Alice", "text": "done"}],
                "display_name": "Alice",
            },
            "export",
        )
        self.assertEqual(out["chat_status"], "completed_full")

    def test_active_group_timer_completed(self):
        started = datetime.now() - timedelta(minutes=10)
        group_info = {"created_at": started}
        out = compute_chat_status(
            _Session(),
            group_info,
            "p1",
            {
                "group_id": "GRP-ACTIVE",
                "messages": [{"sender": "Bob", "text": "hi"}],
                "display_name": "Bob",
            },
            "page_unload",
        )
        self.assertEqual(out["chat_status"], "completed_full")

    def test_active_group_left_early_with_messages(self):
        started = datetime.now() - timedelta(minutes=1)
        group_info = {"created_at": started}
        out = compute_chat_status(
            _Session(),
            group_info,
            "p1",
            {
                "group_id": "GRP-ACTIVE",
                "messages": [{"sender": "Bob", "text": "hi"}],
                "display_name": "Bob",
            },
            "ws_close",
        )
        self.assertEqual(out["chat_status"], "left_early")


if __name__ == "__main__":
    unittest.main()
