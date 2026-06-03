"""Research log captures full system prompts and mode-2 router text."""

import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import chat_log
from chat_log import log_llm_call, serialize_llm_messages


class TestLlmLogging(unittest.TestCase):
    def test_serialize_llm_messages_joins_system_blocks(self):
        messages = [
            {"role": "system", "content": "Identity block"},
            {"role": "system", "content": "Room context"},
            {"role": "user", "content": "Latest from c: hello"},
        ]
        out = serialize_llm_messages(messages)
        self.assertIn("Identity block", out["system_prompt_full"])
        self.assertIn("Room context", out["system_prompt_full"])
        self.assertEqual(out["system_block_count"], 2)
        self.assertIn("hello", out["user_message"])

    def test_log_llm_call_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat_log.CHAT_LOG_DIR = tmp
            log_llm_call(
                "SES-T",
                "GRP-T",
                "intent_router_request",
                actor="orchestrator",
                system_prompt_full="Router system text",
                extra={"call_type": "intent_router", "session_mode": 2},
            )
            path = os.path.join(tmp, "GRP-T.jsonl")
            self.assertTrue(os.path.exists(path))
            row = json.loads(open(path, encoding="utf-8").read().strip())
            self.assertEqual(row["event_type"], "intent_router_request")
            self.assertEqual(row["details"]["system_prompt_full"], "Router system text")


class TestAnalyzeIntentLogging(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_intent_logs_router_before_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat_log.CHAT_LOG_DIR = tmp
            bots = [{"name": "a", "prompt": "Persona A"}, {"name": "b", "prompt": "Persona B"}]
            with patch(
                "bot_manager.create_chat_completion",
                new_callable=AsyncMock,
                return_value="a",
            ):
                from bot_manager import analyze_intent

                chosen = await analyze_intent(
                    "hey @a",
                    bots,
                    "history line",
                    session_id="SES-1",
                    group_id="GRP-1",
                )
            self.assertEqual(chosen, "a")
            events = chat_log.load_chat_log_events("GRP-1")
            types = [e["event_type"] for e in events]
            self.assertIn("intent_router_request", types)
            self.assertIn("intent_router_result", types)
            req = next(e for e in events if e["event_type"] == "intent_router_request")
            self.assertIn("Persona A", req["details"]["system_prompt_full"])
            self.assertIn("AVAILABLE PERSONAS", req["details"]["system_prompt_full"])


if __name__ == "__main__":
    unittest.main()
