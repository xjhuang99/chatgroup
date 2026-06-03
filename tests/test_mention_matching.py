"""@mention detection for mode 3 bots and human notify lists."""

import unittest

from bot_interaction import bots_for_message, message_mentions_name, parse_at_mentions


class _Session:
    session_mode = 3
    bots = [{"name": "a"}, {"name": "b"}]


class TestMentionMatching(unittest.TestCase):
    def test_at_mention_case_insensitive(self):
        self.assertTrue(message_mentions_name("@A hello", "a", require_at=True))
        self.assertTrue(message_mentions_name("hey @b!", "b", require_at=True))
        self.assertFalse(message_mentions_name("@ab", "a", require_at=True))

    def test_mode3_bots_for_message(self):
        bots = bots_for_message(_Session(), "@B can you help?")
        self.assertEqual([b["name"] for b in bots], ["b"])

    def test_parse_at_mentions_includes_humans(self):
        names = parse_at_mentions("@c and @A", ["a", "b", "c"])
        self.assertEqual(set(names), {"a", "c"})

    def test_two_human_names_only_at(self):
        self.assertEqual(parse_at_mentions("hi @d", ["c", "d"]), ["d"])


if __name__ == "__main__":
    unittest.main()
