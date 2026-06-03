"""Researcher account registration and spend cap defaults."""

import os
import tempfile
import unittest

import account_store as astore


class TestAccountStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        self._orig = astore._ACCOUNTS_FILE
        astore._ACCOUNTS_FILE = self._tmp.name

    def tearDown(self):
        astore._ACCOUNTS_FILE = self._orig
        if os.path.exists(self._tmp.name):
            os.unlink(self._tmp.name)

    def test_register_and_login(self):
        out, _ = astore.register_account("tester@ust.hk", password="secretpass1")
        self.assertEqual(out["email"], "tester@ust.hk")
        self.assertTrue(out["username"])
        rec = astore.verify_account_login(out["username"], "secretpass1")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["account_id"], out["account_id"])

    def test_default_spend_cap_200(self):
        out, _ = astore.register_account("cap@ust.hk", password="secretpass2")
        self.assertEqual(out["spend_cap_usd"], 200.0)


if __name__ == "__main__":
    unittest.main()
