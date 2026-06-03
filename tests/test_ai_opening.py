"""AI room opener: fixed hi after lead delay."""

import unittest
from unittest.mock import AsyncMock, patch

from session_runtime import send_ai_opening_message


class TestAiOpening(unittest.IsolatedAsyncioTestCase):
    async def test_opening_uses_hi_after_delay(self):
        broadcast = AsyncMock()
        session = type(
            "S",
            (),
            {"bots": [{"name": "a"}], "opening_delay_seconds": 2.0, "default_opening_text": "hi"},
        )()
        group_info = {}
        bot = type("B", (), {"name": "a"})()

        with patch("session_runtime.match_manager") as mm, patch(
            "session_runtime.get_or_create_context"
        ), patch("session_runtime.get_context", return_value=None), patch(
            "session_runtime.get_or_create_bot_from_cfg", return_value=bot
        ), patch(
            "session_runtime.asyncio.sleep", new_callable=AsyncMock
        ) as sleep_mock, patch(
            "session_runtime.save_message", new_callable=AsyncMock
        ), patch(
            "session_runtime.cache_manager"
        ):
            mm.get_session.return_value = session
            mm.get_group_info.return_value = group_info
            mm.resolve_history_limit.return_value = 100

            result = await send_ai_opening_message("SES", "GRP", {"name": "a"}, "a", broadcast)

        self.assertEqual(result, ("a", "hi"))
        sleep_mock.assert_awaited_once_with(2.0)
        broadcast.assert_awaited_once()
        payload = broadcast.await_args[0][2]
        self.assertEqual(payload["text"], "hi")


if __name__ == "__main__":
    unittest.main()
