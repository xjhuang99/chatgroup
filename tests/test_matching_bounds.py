"""Min/max humans per group — forming groups and overflow to next group."""

import unittest

from match_manager import MatchManager, SessionConfig, normalize_human_group_bounds


class TestMatchingBounds(unittest.TestCase):
    def setUp(self):
        self.mm = MatchManager()
        self.mm.sessions.clear()
        self.mm.forming_fifo.clear()
        self.mm.forming_stratified.clear()
        self.mm.user_locations.clear()

    def _session(self, min_h: int, max_h: int) -> str:
        sid = "SES-BOUNDS"
        cfg = SessionConfig(sid, "Bounds test", max_h)
        cfg.min_humans_per_group = min_h
        cfg.max_humans_per_group = max_h
        self.mm.sessions[sid] = cfg
        self.mm.forming_fifo[sid] = []
        self.mm.forming_stratified[sid] = {}
        return sid

    def test_normalize_fixed_from_group_size(self):
        self.assertEqual(normalize_human_group_bounds(group_size=2), (2, 2))

    def test_fixed_two_waits_until_second(self):
        sid = self._session(2, 2)
        self.assertIsNone(self.mm.add_to_queue(sid, "u1"))
        gid = self.mm.add_to_queue(sid, "u2")
        self.assertIsNotNone(gid)
        self.assertEqual(len(self.mm.get_group_info(sid, gid)["members"]), 2)

    def test_overflow_starts_new_forming_group(self):
        sid = self._session(2, 2)
        self.mm.add_to_queue(sid, "u1")
        g1 = self.mm.add_to_queue(sid, "u2")
        self.assertIsNone(self.mm.add_to_queue(sid, "u3"))
        g2 = self.mm.add_to_queue(sid, "u4")
        self.assertNotEqual(g1, g2)

    def test_min_one_starts_solo(self):
        sid = self._session(1, 3)
        gid = self.mm.add_to_queue(sid, "solo")
        self.assertIsNotNone(gid)
        self.assertEqual(self.mm.get_group_info(sid, gid)["members"], ["solo"])

    def test_min_two_max_four_starts_at_two(self):
        sid = self._session(2, 4)
        self.assertIsNone(self.mm.add_to_queue(sid, "a"))
        g = self.mm.add_to_queue(sid, "b")
        self.assertIsNotNone(g)
        self.assertEqual(set(self.mm.get_group_info(sid, g)["members"]), {"a", "b"})


if __name__ == "__main__":
    unittest.main()
