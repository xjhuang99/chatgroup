"""Tests for /api/match session validation."""

import unittest

from fastapi.testclient import TestClient

from main import app


class TestMatchingApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_invalid_session_returns_not_found(self):
        res = self.client.get(
            "/api/match",
            params={"session_id": "SES-DOES-NOT-EXIST-99999", "uid": "test_user_1"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "session_not_found")
        self.assertIn("session_id", data)
        self.assertNotEqual(data["status"], "waiting")

    def test_valid_session_can_return_waiting(self):
        from match_manager import match_manager

        if not match_manager.sessions:
            self.skipTest("No sessions loaded in config")
        session_id = next(iter(match_manager.sessions.keys()))
        uid = f"unittest_wait_{session_id}"
        res = self.client.get(
            "/api/match",
            params={"session_id": session_id, "uid": uid},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn(data["status"], ("waiting", "matched"))
        match_manager.remove_from_queue(session_id, uid)


if __name__ == "__main__":
    unittest.main()
