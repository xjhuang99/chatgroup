"""Auto human letters after bot names when participant_names is empty."""

import unittest

from match_manager import MatchManager
from participant_naming import participant_name_pool, pick_human_display_name


class TestParticipantNaming(unittest.TestCase):
    def test_pool_skips_bot_letters(self):
        mm = MatchManager()
        sid = mm.create_session(
            name="Auto letters",
            group_size=2,
            bot_enabled=True,
            bots=[{"name": "a"}, {"name": "b"}],
            participant_names=[],
            min_humans_per_group=2,
            max_humans_per_group=2,
        )
        session = mm.get_session(sid)
        self.assertEqual(participant_name_pool(session, 2), ["c", "d"])

    def test_create_group_assigns_after_bots(self):
        mm = MatchManager()
        sid = mm.create_session(
            name="Two humans",
            group_size=2,
            bot_enabled=True,
            bots=[{"name": "a"}, {"name": "b"}],
            participant_names=[],
            min_humans_per_group=2,
            max_humans_per_group=2,
        )
        gid = mm.create_group(sid, "GRP-LETTERS", members=["u1", "u2"])
        info = mm.get_group_info(sid, gid)
        self.assertEqual(set(info["member_names"].values()), {"c", "d"})

    def test_explicit_names_unchanged(self):
        mm = MatchManager()
        sid = mm.create_session(
            name="Explicit",
            group_size=1,
            bot_enabled=True,
            bots=[{"name": "a"}],
            participant_names=["x"],
            min_humans_per_group=1,
            max_humans_per_group=1,
        )
        session = mm.get_session(sid)
        self.assertEqual(pick_human_display_name(session, set()), "x")

    def test_queue_roster_uses_auto_letters(self):
        mm = MatchManager()
        sid = mm.create_session(
            name="Wait",
            group_size=2,
            bot_enabled=True,
            bots=[{"name": "a"}, {"name": "b"}],
            participant_names=[],
            min_humans_per_group=2,
            max_humans_per_group=2,
        )
        mm.add_to_queue(sid, "u1")
        prog = mm.get_queue_progress(sid, "u1")
        self.assertIsNotNone(prog)
        self.assertEqual(prog["teammate_display_names"], ["c", "d"])


if __name__ == "__main__":
    unittest.main()
