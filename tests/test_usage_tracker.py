"""Usage cost estimation, spend caps, and ended-group status (regression)."""

import os
import tempfile
import unittest

import usage_tracker as ut


class TestUsageTracker(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        ut._LEDGER_DIR = self._tmpdir
        ut._LEDGER_FILE = os.path.join(self._tmpdir, "usage_ledger.jsonl")
        ut._ROLLUP_FILE = os.path.join(self._tmpdir, "usage_rollups.json")

    def test_estimate_cost_positive(self):
        cost = ut.estimate_cost_usd("gpt-4o", 1000, 500)
        self.assertGreater(cost, 0)

    def test_record_and_rollup(self):
        ut.record_usage(
            session_id="SES-T",
            group_id="GRP-T",
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=200,
            call_type="test",
        )
        g = ut.get_group_usage("GRP-T")
        self.assertEqual(g.get("api_calls"), 1)
        self.assertGreater(g.get("spend_usd", 0), 0)

    def test_spend_exceeds_small_cap(self):
        ut.record_usage(
            session_id="SES-C",
            group_id="GRP-C",
            model="gpt-5",
            prompt_tokens=5_000_000,
            completion_tokens=1_000_000,
            call_type="test",
        )
        spent = ut.get_group_spend_usd("GRP-C")
        self.assertGreaterEqual(spent, 0.01)


class TestEndedGroupStatus(unittest.TestCase):
    def test_empty_group_info_not_never_joined(self):
        from session_runtime import compute_chat_status

        class S:
            group_chat_duration_minutes = 5

        out = compute_chat_status(
            S(),
            {},
            "p1",
            {"group_id": "GRP-X", "messages": [{"sender": "p1", "text": "hi"}], "display_name": "p1"},
            "duration_limit",
        )
        self.assertEqual(out["chat_status"], "completed_full")


if __name__ == "__main__":
    unittest.main()
