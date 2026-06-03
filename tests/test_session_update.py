"""Dashboard session update: disk save, spend cap on active groups, session_mode."""

import unittest
from unittest.mock import patch

from match_manager import MatchManager, SessionConfig


class TestSessionUpdate(unittest.TestCase):
    def setUp(self):
        self.mm = MatchManager()
        self.mm.sessions.clear()
        self.mm.active_rooms.clear()
        cfg = SessionConfig("SES-TEST1", "Test", group_size=2)
        cfg.group_spend_cap_usd = 8.0
        cfg.session_mode = 1
        self.mm.sessions["SES-TEST1"] = cfg
        self.mm.active_rooms["SES-TEST1"] = {
            "GRP-1": {"members": ["u1"], "spend_cap_usd": 8.0},
        }

    def test_update_spend_cap_propagates_to_active_group(self):
        ok = self.mm.update_session("SES-TEST1", {"group_spend_cap_usd": 12.5})
        self.assertTrue(ok)
        self.assertEqual(self.mm.sessions["SES-TEST1"].group_spend_cap_usd, 12.5)
        self.assertEqual(
            self.mm.active_rooms["SES-TEST1"]["GRP-1"]["spend_cap_usd"],
            12.5,
        )

    def test_invalid_session_mode_raises(self):
        with self.assertRaises(ValueError):
            self.mm.update_session("SES-TEST1", {"session_mode": 9})

    def test_update_returns_false_when_save_fails(self):
        with patch.object(self.mm, "save_all_sessions", return_value=False):
            ok = self.mm.update_session("SES-TEST1", {"session_name": "Renamed"})
        self.assertFalse(ok)
        self.assertEqual(self.mm.sessions["SES-TEST1"].name, "Renamed")


if __name__ == "__main__":
    unittest.main()
