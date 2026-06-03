import unittest

from actr.room_context import (
    commit_room_message,
    get_context_version,
    init_room_context_state,
    is_context_stale,
    refresh_user_text_suffix,
    transcript_note_for_refresh,
)


class RoomContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_bump_only_affects_other_bots(self):
        group_info = {}
        init_room_context_state(group_info)
        await commit_room_message("GRP-1", "a", "hello from a", group_info)
        self.assertEqual(get_context_version(group_info), 1)
        self.assertFalse(is_context_stale(group_info, 0, "a"))
        self.assertTrue(is_context_stale(group_info, 0, "b"))

    def test_refresh_suffix_and_transcript_note(self):
        group_info = {
            "last_context_bump_sender": "b",
            "last_context_bump_text": "new idea",
        }
        suffix = refresh_user_text_suffix(group_info, 1)
        self.assertIn("Someone just said", suffix)
        self.assertIn("new idea", suffix)
        note = transcript_note_for_refresh(1, "b", "new idea")
        self.assertIn("mode4 refresh", note)
        self.assertIn("b", note)


if __name__ == "__main__":
    unittest.main()
