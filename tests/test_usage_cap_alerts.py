"""Cap threshold alerts: 80% warn once, 100% critical once."""

import os
import tempfile
import unittest
from unittest.mock import patch

import usage_alerts as ua


class TestCapThresholdAlerts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        ua._STATE_FILE = os.path.join(self.tmp, "usage_alert_state.json")
        self.sent: list = []

    def _capture_send(self, subject, body, to_addrs):
        self.sent.append({"subject": subject, "to": list(to_addrs), "body": body})
        return True

    @patch.dict(os.environ, {"SMTP_HOST": "smtp.test", "ALERT_EMAIL_TO": "ops@test.org"})
    @patch.object(ua, "_account_email", return_value="researcher@test.org")
    def test_level1_at_80_percent(self, _email):
        def fake_send(subject, body, to_addrs):
            return self._capture_send(subject, body, to_addrs)

        with patch.object(ua, "_send_email", fake_send):
            state = {}
            ua._evaluate_cap_scope(
                state,
                "group:GRP-1",
                spent=8.0,
                cap=10.0,
                session_id="SES-1",
                group_id="GRP-1",
                last_call_cost=0.01,
                owner_account_id="ACC-1",
            )
        self.assertTrue(state["group:GRP-1"]["warn_sent"])
        self.assertFalse(state["group:GRP-1"]["critical_sent"])
        subjects = [m["subject"] for m in self.sent]
        self.assertIn(ua.CAP_LEVEL1_RESEARCHER_SUBJECT, subjects)
        self.assertIn(ua.CAP_LEVEL1_OPS_SUBJECT, subjects)
        owner_mails = [m for m in self.sent if "researcher@test.org" in m["to"]]
        ops_mails = [m for m in self.sent if "ops@test.org" in m["to"]]
        self.assertEqual(len(owner_mails), 1)
        self.assertEqual(len(ops_mails), 1)
        self.assertIn("80%", owner_mails[0]["body"])

    @patch.dict(os.environ, {"SMTP_HOST": "smtp.test", "ALERT_EMAIL_TO": "ops@test.org"})
    @patch.object(ua, "_account_email", return_value="researcher@test.org")
    def test_level2_skips_duplicate_level1(self, _email):
        def fake_send(subject, body, to_addrs):
            return self._capture_send(subject, body, to_addrs)

        with patch.object(ua, "_send_email", fake_send):
            state = {"group:GRP-2": {"warn_sent": True, "critical_sent": False}}
            ua._evaluate_cap_scope(
                state,
                "group:GRP-2",
                spent=10.0,
                cap=10.0,
                session_id="SES-1",
                group_id="GRP-2",
                last_call_cost=0.01,
                owner_account_id="ACC-1",
            )
        self.assertTrue(state["group:GRP-2"]["critical_sent"])
        level1_new = [m for m in self.sent if "warning" in m["subject"].lower()]
        level2 = [m for m in self.sent if "limit reached" in m["subject"].lower()]
        self.assertEqual(len(level1_new), 0)
        self.assertEqual(len(level2), 2)

    @patch.dict(os.environ, {"SMTP_HOST": "smtp.test", "ALERT_EMAIL_TO": "ops@test.org"})
    def test_below_80_no_email(self):
        def fake_send(subject, body, to_addrs):
            return self._capture_send(subject, body, to_addrs)

        with patch.object(ua, "_send_email", fake_send):
            state = {}
            ua._evaluate_cap_scope(
                state,
                "account:ACC-X",
                spent=5.0,
                cap=200.0,
                session_id="",
                group_id="",
                last_call_cost=0.01,
                owner_account_id=None,
            )
        self.assertEqual(len(self.sent), 0)


if __name__ == "__main__":
    unittest.main()
