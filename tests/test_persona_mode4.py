import unittest

from bot_manager import persona_mode4_reply_threshold, persona_mode4_should_reply
from chat_log import resolve_qualtrics_export_text


class PersonaMode4Tests(unittest.TestCase):
    def test_threshold_no_random_roll(self):
        cfg = {"mode_4_threshold": 0.5}
        self.assertTrue(persona_mode4_should_reply(cfg, 0.5))
        self.assertTrue(persona_mode4_should_reply(cfg, 0.9))
        self.assertFalse(persona_mode4_should_reply(cfg, 0.49))

    def test_default_threshold(self):
        self.assertEqual(persona_mode4_reply_threshold({}), 0.5)

    def test_qualtrics_log_mode(self):
        class S:
            qualtrics_log_mode = "full"

        self.assertIn("RESEARCH", resolve_qualtrics_export_text(S(), "hi", "=== ACTR RESEARCH CHAT LOG ===\n"))
        S.qualtrics_log_mode = "transcript"
        self.assertEqual(resolve_qualtrics_export_text(S(), "line1", "full"), "line1")


if __name__ == "__main__":
    unittest.main()
