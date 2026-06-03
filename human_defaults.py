"""
Canonical example defaults for new sessions, API fallbacks, and Admin ★ Example.
Keep templates/admin.html chat model lists in sync when changing values here.
"""

import os
from typing import Any, Dict, Optional, Tuple

# OpenAI chat models (keep templates/admin.html GPT_CHAT_MODELS in sync)
GPT_CHAT_MODELS: Tuple[str, ...] = ("gpt-5.5", "gpt-5", "gpt-4o")
DEFAULT_GPT_CHAT_MODEL = "gpt-5"

# DeepSeek (OpenAI-compatible API — set DEEPSEEK_API_KEY in .env)
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_CHAT_MODELS: Tuple[str, ...] = ("deepseek-chat", "deepseek-reasoner")
DEFAULT_DEEPSEEK_CHAT_MODEL = "deepseek-chat"


def default_llm_provider() -> str:
    """Default provider when model is unset; LLM_PROVIDER=deepseek|openai (default deepseek)."""
    raw = (os.getenv("LLM_PROVIDER") or "deepseek").strip().lower()
    if raw in ("openai", "deepseek"):
        return raw
    return "deepseek"


def active_llm_provider() -> str:
    """Alias for default_llm_provider (session defaults / aux routing)."""
    return default_llm_provider()


def provider_for_model(model: Optional[str]) -> str:
    """Route API client by model id; GPT/o* → OpenAI, deepseek* → DeepSeek."""
    m = (model or "").strip().lower()
    if m.startswith("deepseek"):
        return "deepseek"
    if m.startswith("gpt") or m.startswith("o"):
        return "openai"
    return default_llm_provider()


def default_chat_model() -> str:
    if default_llm_provider() == "openai":
        env = (os.getenv("OPENAI_CHAT_MODEL") or "").strip()
        if env in GPT_CHAT_MODELS:
            return env
        return DEFAULT_GPT_CHAT_MODEL
    return (os.getenv("DEEPSEEK_CHAT_MODEL") or DEFAULT_DEEPSEEK_CHAT_MODEL).strip()


def normalize_gpt_chat_model(model: Optional[str]) -> str:
    """Return a whitelisted model id (DeepSeek or OpenAI)."""
    m = (model or "").strip()
    if m in DEEPSEEK_CHAT_MODELS:
        return m
    if m in GPT_CHAT_MODELS:
        return m
    return default_chat_model()


HUMAN_LIKE_PROMPT = (
    "You are a participant in a casual climate group chat. "
    "Goal: help the group produce 3 concrete solutions everyone agrees on within 3 minutes. "
    "Treat all teammates the same; you can say hi. "
    "Jump into the discussion and deliver your first opinion quickly. "
    "When asked for an idea, give 1 concrete action (not generic) at a time. "
    "Finally the group should confirm the best three and move to the final step. "
    "Write like texting: short phrases, not full sentences; fragments, typos, and abbreviations are preferred. "
    "Use normal capitalization only—never ALL CAPS. "
    "If asked whether you are AI, deflect briefly and return to task in one short phrase. "
    "Sound lazy, minimize words, and push to finalize answers quickly. "
    "Do not say let's brainstorm—just give solutions. "
    "Do not always repeat others."
)

HUMAN_LIKE_SESSION: Dict[str, Any] = {
    "session_mode": 1,
    "bot_reply_on_any_message": True,
    "max_chain_depth": 2,
    "use_mentions": False,
    "mention_prob": 0.0,
    "self_correction_prob": 0.0,
    "ai_starts_conversation": True,
    "opening_delay_seconds": 2.0,
    "default_opening_text": "hi",
    "style_mimic_enabled": False,
    "turn_mode": "none",
}

# Session mode 4: parallel bot API + refresh when a peer posts (see actr/room_context.py)
MODE_4_SESSION_DEFAULTS: Dict[str, Any] = {
    "parallel_start_jitter_sec": 1.5,
    "rethink_seconds": 2.0,
    "max_refresh_attempts": 2,
}

# Qualtrics: transcript = chat lines only; full = research log (prompts, decisions, notes)
QUALTRICS_LOG_TRANSCRIPT = "transcript"
QUALTRICS_LOG_FULL = "full"

HUMAN_LIKE_BOT: Dict[str, Any] = {
    "prompt": HUMAN_LIKE_PROMPT,
    "model": DEFAULT_DEEPSEEK_CHAT_MODEL,
    "mode": 3,
    "avatar_type": "human",
    "disclosed_ai_allowed": False,
    "delay_seconds": 5,
    "typing_cps": 2,
    "temperature": 0.7,
    "context_max_chars": 100_000,
    "idle_threshold": 50,
    "skip_rate": 0.15,
    "min_words": 1,
    "max_words": 20,
    "length_variation": True,
    "emoji_enabled": False,
}


def apply_human_session_defaults(session) -> None:
    for key, value in HUMAN_LIKE_SESSION.items():
        setattr(session, key, value)
    for key, value in MODE_4_SESSION_DEFAULTS.items():
        setattr(session, key, value)
    session.qualtrics_log_mode = QUALTRICS_LOG_TRANSCRIPT
