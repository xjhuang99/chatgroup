"""Queue progress API: 2 humans + AI bots — humans only count toward min/max."""

import unittest

from fastapi.testclient import TestClient

from main import app
from match_manager import MatchManager, SessionConfig


class TestMatchingQueueProgress(unittest.TestCase):
    def setUp(self):
        self.mm = MatchManager()
        self.mm.sessions.clear()
        self.mm.forming_fifo.clear()
        self.mm.forming_stratified.clear()
        self.mm.user_locations.clear()
        self.mm.active_rooms.clear()
        self.sid = "SES-QPROG"
        cfg = SessionConfig(self.sid, "Two humans + AI", 2)
        cfg.min_humans_per_group = 2
        cfg.max_humans_per_group = 2
        cfg.bot_enabled = True
        cfg.bots = [{"name": "a"}, {"name": "b"}]
        self.mm.sessions[self.sid] = cfg
        self.mm.forming_fifo[self.sid] = []
        self.mm.forming_stratified[self.sid] = {}

    def test_queue_progress_first_human(self):
        self.assertIsNone(self.mm.add_to_queue(self.sid, "human_1"))
        prog = self.mm.get_queue_progress(self.sid, "human_1")
        self.assertIsNotNone(prog)
        self.assertEqual(prog["humans_matched"], 1)
        self.assertEqual(prog["min_humans_per_group"], 2)
        self.assertEqual(prog["ai_teammates_ready"], 2)

    def test_second_human_opens_room_humans_only(self):
        self.mm.add_to_queue(self.sid, "human_1")
        gid = self.mm.add_to_queue(self.sid, "human_2")
        self.assertIsNotNone(gid)
        members = self.mm.get_group_info(self.sid, gid)["members"]
        self.assertEqual(members, ["human_1", "human_2"])
        self.assertNotIn("a", members)

    def test_match_api_waiting_payload(self):
        from match_manager import match_manager

        match_manager.sessions[self.sid] = self.mm.sessions[self.sid]
        match_manager.forming_fifo[self.sid] = []
        match_manager.forming_stratified[self.sid] = {}
        match_manager.user_locations.clear()
        match_manager.active_rooms[self.sid] = {}

        client = TestClient(app)
        uid = "api_human_1"
        res = client.get(
            "/api/match",
            params={"session_id": self.sid, "uid": uid},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "waiting")
        self.assertEqual(data["humans_matched"], 1)
        self.assertEqual(data["min_humans_per_group"], 2)
        self.assertEqual(data["ai_teammates_ready"], 2)
        match_manager.remove_from_queue(self.sid, uid)

    def test_min_one_human_does_not_wait(self):
        cfg = SessionConfig("SES-SOLO", "Solo + AI", 1)
        cfg.min_humans_per_group = 1
        cfg.max_humans_per_group = 2
        cfg.bot_enabled = True
        cfg.bots = [{"name": "bot_a"}]
        self.mm.sessions["SES-SOLO"] = cfg
        self.mm.forming_fifo["SES-SOLO"] = []
        gid = self.mm.add_to_queue("SES-SOLO", "solo_user")
        self.assertIsNotNone(gid)
        self.assertEqual(self.mm.get_group_info("SES-SOLO", gid)["members"], ["solo_user"])


if __name__ == "__main__":
    unittest.main()
