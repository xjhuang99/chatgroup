"""Bot queue stops when a room is cancelled."""

import unittest

from bot_queue import bot_response_queue


class TestBotQueueCancel(unittest.TestCase):
    def test_cancel_room_flag(self):
        bot_response_queue.cancel_room("GRP-CANCEL-TEST")
        self.assertTrue(bot_response_queue.is_room_cancelled("GRP-CANCEL-TEST"))


if __name__ == "__main__":
    unittest.main()
