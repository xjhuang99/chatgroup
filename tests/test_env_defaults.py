"""Env default constants and accessors stay aligned."""

import os
import unittest
from unittest.mock import patch

import env_defaults as ed


class TestEnvDefaults(unittest.TestCase):
    def test_documented_constants(self):
        self.assertEqual(ed.DEFAULT_GROUP_SPEND_CAP_USD, 8.0)
        self.assertEqual(ed.DEFAULT_ACCOUNT_SPEND_CAP_USD, 200.0)
        self.assertEqual(ed.DEFAULT_ALERT_HOURLY_SPEND_USD, 40.0)
        self.assertEqual(ed.DEFAULT_ALERT_GROUP_BURST_USD, 15.0)
        self.assertEqual(ed.DEFAULT_ALERT_COOLDOWN_MINUTES, 30)
        self.assertEqual(ed.DEFAULT_ALERT_CAP_WARN_RATIO, 0.8)

    @patch.dict(os.environ, {}, clear=True)
    def test_accessors_without_env(self):
        self.assertEqual(ed.default_group_spend_cap_usd(), 8.0)
        self.assertEqual(ed.default_account_spend_cap_usd(), 200.0)
        self.assertIsNone(ed.default_session_spend_cap_usd())
        self.assertEqual(ed.default_alert_hourly_spend_usd(), 40.0)
        self.assertEqual(ed.default_alert_group_burst_usd(), 15.0)
        self.assertEqual(ed.default_alert_cooldown_minutes(), 30)
        self.assertEqual(ed.default_alert_cap_warn_ratio(), 0.8)

    @patch.dict(
        os.environ,
        {
            "GROUP_SPEND_CAP_USD": "12",
            "ACCOUNT_SPEND_CAP_USD": "150",
            "SESSION_SPEND_CAP_USD": "50",
            "ALERT_HOURLY_SPEND_USD": "99",
            "ALERT_GROUP_BURST_USD": "22",
            "ALERT_COOLDOWN_MINUTES": "5",
            "ALERT_CAP_WARN_RATIO": "0.75",
        },
        clear=True,
    )
    def test_accessors_read_env(self):
        self.assertEqual(ed.default_group_spend_cap_usd(), 12.0)
        self.assertEqual(ed.default_account_spend_cap_usd(), 150.0)
        self.assertEqual(ed.default_session_spend_cap_usd(), 50.0)
        self.assertEqual(ed.default_alert_hourly_spend_usd(), 99.0)
        self.assertEqual(ed.default_alert_group_burst_usd(), 22.0)
        self.assertEqual(ed.default_alert_cooldown_minutes(), 5)
        self.assertEqual(ed.default_alert_cap_warn_ratio(), 0.75)

    @patch.dict(os.environ, {}, clear=True)
    def test_env_defaults_dict_matches_accessors(self):
        d = ed.env_defaults_dict()
        self.assertEqual(d["group_spend_cap_usd"], ed.default_group_spend_cap_usd())
        self.assertEqual(d["account_spend_cap_usd"], ed.default_account_spend_cap_usd())
        self.assertEqual(d["session_spend_cap_usd"], ed.default_session_spend_cap_usd())
        self.assertEqual(d["alert_hourly_spend_usd"], ed.default_alert_hourly_spend_usd())
        self.assertEqual(d["alert_group_burst_usd"], ed.default_alert_group_burst_usd())
        self.assertEqual(d["alert_cooldown_minutes"], ed.default_alert_cooldown_minutes())
        self.assertEqual(d["alert_cap_warn_ratio"], ed.default_alert_cap_warn_ratio())


if __name__ == "__main__":
    unittest.main()
