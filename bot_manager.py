import asyncio
import re
from typing import Optional, Dict, List
from dotenv import load_dotenv
import os
import random

from openai import AsyncOpenAI

# Load environment variables
load_dotenv()

from human_defaults import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_CHAT_MODELS,
    GPT_CHAT_MODELS,
    HUMAN_LIKE_PROMPT,
    default_chat_model,
    default_llm_provider,
    normalize_gpt_chat_model,
    provider_for_model,
)

_openai_client: Optional[AsyncOpenAI] = None
_deepseek_client: Optional[AsyncOpenAI] = None


def log_llm_providers() -> None:
    ds = bool((os.getenv("DEEPSEEK_API_KEY") or "").strip())
    oa = bool((os.getenv("OPENAI_API_KEY") or "").strip())
    default = default_llm_provider()
    print(
        f"🤖 LLM default: {default} | DeepSeek={'on' if ds else 'off'} | "
        f"OpenAI={'on' if oa else 'off'} | per-model routing (gpt-* / deepseek-*)"
    )


def get_llm_client_for_model(model: str) -> AsyncOpenAI:
    """OpenAI SDK client for the provider implied by model id."""
    global _openai_client, _deepseek_client
    if provider_for_model(model) == "openai":
        if _openai_client is None:
            key = (os.getenv("OPENAI_API_KEY") or "").strip()
            if not key:
                raise RuntimeError(
                    "OPENAI_API_KEY is missing in .env (this call uses a GPT model)"
                )
            _openai_client = AsyncOpenAI(api_key=key)
        return _openai_client
    if _deepseek_client is None:
        key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY is missing in .env")
        _deepseek_client = AsyncOpenAI(
            api_key=key,
            base_url=os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL),
        )
    return _deepseek_client


def get_llm_client() -> AsyncOpenAI:
    """Client for the configured default provider / model."""
    return get_llm_client_for_model(default_chat_model())


def resolve_chat_model(bot_cfg: Optional[dict] = None) -> str:
    """Per-persona model (Admin whitelist), else env default for active provider."""
    if bot_cfg:
        return normalize_gpt_chat_model(bot_cfg.get("model"))
    return default_chat_model()


def resolve_aux_model() -> str:
    """Orchestrator / scoring calls (lighter default)."""
    ds = (os.getenv("DEEPSEEK_AUX_MODEL") or "").strip()
    if ds in DEEPSEEK_CHAT_MODELS:
        return ds
    oa = (os.getenv("OPENAI_AUX_MODEL") or "").strip()
    if oa in GPT_CHAT_MODELS:
        return oa
    if default_llm_provider() == "openai":
        return "gpt-5-mini"
    return "deepseek-chat"

# Default system prompt when no specific instructions are provided
DEFAULT_SYSTEM_PROMPT = HUMAN_LIKE_PROMPT

HUMAN_OUTPUT_RULES = """
STRICT CHAT FORMAT (always follow):
- You are a teammate in a group chat. Stay in character; do not mention being an AI system unless asked.
- Speak ONLY as yourself ({bot_name}). Never write lines for other people.
- Never prefix your message with "{bot_name}:" or roleplay a script (no "a: ... b: ...").
- Prefer short phrases over full sentences; fragments, typos, and abbreviations preferred (texting style).
- Normal capitalization only—never ALL CAPS or shouting.
- Maximum ~35 words unless the latest message clearly asks for a long answer.
- No "Hello team", no speeches, no essays, no bullet/numbered lists unless explicitly requested.
- Do not repeat or summarize what someone just said; add something new or react briefly.
- Do not ask a question in every reply — often just agree, joke, or add one short point.
- Avoid interview tone ("What do you think?", "Any thoughts on…") unless the room is stuck.
- Avoid formal essay words (e.g. "individual lifestyle changes", "tackle", "contribute to fighting").
- Other participants in the room: {peers}. You are not them. Treat every sender the same.
- You are an independent participant with your own views; never imply you share a hidden controller with other bots.
"""


async def create_chat_completion(
    *,
    model: str,
    messages: List[Dict],
    cap_tokens: int,
    temperature: float = 0.7,
    session_id: Optional[str] = None,
    group_id: Optional[str] = None,
    call_type: str = "chat",
    request_id: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> str:
    """OpenAI chat completion with model-specific token param names and usage tracking."""
    import time

    from usage_tracker import (
        SpendCapExceeded,
        check_can_spend,
        estimate_cost_usd,
        record_usage,
        usage_from_completion,
    )

    if group_id and session_id:
        allowed, reason = check_can_spend(session_id, group_id)
        if not allowed:
            if request_id:
                from chat_log import log_llm_error

                log_llm_error(
                    session_id,
                    group_id,
                    request_id=request_id,
                    error_type="spend_cap",
                    message=reason or "spend cap",
                    extra={"call_type": call_type, "turn_id": turn_id},
                )
            raise SpendCapExceeded(reason)

    kwargs: Dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if model.startswith("gpt-5") or model.startswith("o"):
        kwargs["max_completion_tokens"] = cap_tokens
    else:
        kwargs["max_tokens"] = cap_tokens
        if not model.startswith("deepseek"):
            kwargs["frequency_penalty"] = 0.35
            kwargs["presence_penalty"] = 0.2
    t0 = time.perf_counter()
    try:
        response = await get_llm_client_for_model(model).chat.completions.create(**kwargs)
        text = response.choices[0].message.content.strip()
    except Exception as e:
        if request_id and session_id and group_id:
            from chat_log import log_llm_error

            log_llm_error(
                session_id,
                group_id,
                request_id=request_id,
                error_type="api_error",
                message=str(e),
                extra={"call_type": call_type, "model": model, "turn_id": turn_id},
            )
        raise

    latency_ms = (time.perf_counter() - t0) * 1000.0
    if group_id and session_id:
        prompt_t, completion_t = usage_from_completion(response, messages)
        cost = estimate_cost_usd(model, prompt_t, completion_t)
        record_usage(
            session_id=session_id,
            group_id=group_id,
            model=model,
            prompt_tokens=prompt_t,
            completion_tokens=completion_t,
            call_type=call_type,
        )
        if request_id:
            from chat_log import log_api_usage

            log_api_usage(
                session_id,
                group_id,
                request_id,
                model=model,
                call_type=call_type,
                prompt_tokens=prompt_t,
                completion_tokens=completion_t,
                cost_usd=cost,
                latency_ms=latency_ms,
                extra={"turn_id": turn_id} if turn_id else None,
            )
    return text

# Short fallbacks when the AI API is unavailable

# Fallback replies used when the AI API is unavailable
FALLBACK_REPLIES = [
    "What do you think of it?",
    "Well, I'm not sure...",
    "That's an interesting point. What does everyone else think?",
    "Hmm, I need a moment to think about that.",
    "Could you tell me more?",
    "I see what you mean. What's your take on it?",
    "That's worth considering. Anyone else have thoughts?",
    "Not sure I have a strong opinion — what about you?",
]


def build_style_rules(bot_name: str, peer_names: Optional[List[str]] = None) -> str:
    peers = ", ".join(peer_names) if peer_names else "(other teammates)"
    return HUMAN_OUTPUT_RULES.format(bot_name=bot_name, peers=peers)


def sanitize_bot_reply(
    text: str,
    bot_name: str,
    peer_names: Optional[List[str]] = None,
    max_words: int = 45,
    allow_emoji: bool = True,
) -> str:
    """Strip multi-speaker scripts, lists, and runaway length."""
    if not text:
        return text

    out_lines: List[str] = []
    all_names = {bot_name.lower()}
    if peer_names:
        all_names.update(n.lower() for n in peer_names if n)

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.+)$", line)
        if m:
            speaker, content = m.group(1), m.group(2).strip()
            if speaker.lower() == bot_name.lower():
                out_lines.append(content)
            continue
        out_lines.append(line)

    cleaned = " ".join(out_lines).strip() or text.strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    # Drop numbered-list essays unless very short
    if re.search(r"\b[1-5]\.\s", cleaned) and len(cleaned.split()) > max_words // 2:
        before_list = re.split(r"\s*1\.\s", cleaned, maxsplit=1)[0].strip()
        if len(before_list.split()) >= 4:
            cleaned = before_list

    # NOTE: We do not hard-truncate by max_words here. Length is guided via prompt
    # ("within about X words") and bounded by max_tokens.

    if not allow_emoji:
        cleaned = strip_emojis(cleaned)

    return cleaned


def jitter_delay_extra() -> float:
    """Random add-on used by persona modes 2–4 (seconds)."""
    return random.uniform(0.5, 2.5)


def compute_typing_delay_seconds(text: str, typing_cps: float) -> float:
    """Simulate time to type the reply before it appears in chat."""
    cps = max(1.0, min(6.0, float(typing_cps or 4)))
    return max(0.3, min(12.0, len(text or "") / cps))


def api_token_cap_for_words(max_words: int) -> int:
    """OpenAI max_tokens from admin word cap (~1.45 tokens per word)."""
    mw = max(1, int(max_words))
    return min(120, max(15, int(mw * 1.45)))


def emoji_enabled_from_cfg(bot_cfg: dict) -> bool:
    return bool((bot_cfg or {}).get("emoji_enabled", False))


def emoji_style_note(enabled: bool) -> str:
    if enabled:
        return "You may use emojis sparingly when it fits casual texting."
    return "Do not use emoji, emoticons, or ASCII smileys (e.g. :) :D)."


def strip_emojis(text: str) -> str:
    if not text:
        return text
    cleaned = re.sub(
        r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F\u200d]+",
        "",
        text,
        flags=re.UNICODE,
    )
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def pick_reply_word_cap(
    min_words: int = 1,
    max_words: int = 35,
    length_variation: bool = True,
) -> tuple[int, str]:
    """
    Pick target length for this reply (prompt only; no post-hoc truncate to this value).
    Mix on: uniform random in [min, max]. Mix off: always max.
    Returns (target_words, hint for the model).
    """
    min_w = max(1, int(min_words))
    max_w = max(min_w, int(max_words))

    if not length_variation:
        return max_w, f"within about {max_w} words (casual group chat, 1–2 sentences)"

    target = random.randint(min_w, max_w)
    return target, f"within about {target} words (casual group chat, 1–2 sentences)"


def _cap_sentences(text: str, max_sentences: int = 2) -> str:
    # Backwards-compatible shim (no-op). We no longer hard-cap sentences.
    _ = max_sentences
    return (text or "").strip()


class ChatBot:
    """
    Chat Bot Class representing a unique persona.
    Each instance manages its own identity, prompt, and conversation history.
    """

    def __init__(self, room_id: str, name: str, system_prompt: str):
        """
        Initialize the bot with a name and room context.
        """
        self.room_id = room_id
        self.name = name
        
        # Identity injection: Ensure the bot knows its name and role
        identity_instr = (
            f"Your name is {self.name}. Always stay in character as {self.name}. "
            f"You are an independent person in this chat—not controlled by other participants or bots. "
        )
        
        base = DEFAULT_SYSTEM_PROMPT if not system_prompt or not system_prompt.strip() else system_prompt
        self.system_prompt = identity_instr + base + build_style_rules(name)

        self.conversation_history = []
        print(f"✅ Bot '{self.name}' initialized for room {room_id}")

    async def generate_response(
        self,
        user_id: str,
        user_message: str,
        full_context_summary: str,
        temperature: float = 0.7,
        peer_names: Optional[List[str]] = None,
        max_words: int = 35,
        min_words: int = 1,
        length_variation: bool = True,
        style_mimic_hint: Optional[str] = None,
        max_tokens: Optional[int] = None,
        mention_note: Optional[str] = None,
        mention_target: Optional[str] = None,
        emoji_enabled: bool = False,
        model: Optional[str] = None,
        session_id: Optional[str] = None,
        log_meta: Optional[Dict] = None,
    ) -> Optional[str]:
        """
        Generates a response using the full room history provided by the ContextManager.
        Length is controlled in words (admin); max_tokens is derived unless legacy max_tokens is set.
        """
        try:
            target_words, length_hint = pick_reply_word_cap(
                min_words, max_words, length_variation
            )
            cap_tokens = (
                max(15, min(int(max_tokens), 120))
                if max_tokens
                else api_token_cap_for_words(target_words)
            )
            messages = [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "system",
                    "content": (
                        f"Roommates (do not impersonate): {', '.join(peer_names) if peer_names else 'others'}\n"
                        f"Chat so far:\n{full_context_summary or '(just starting)'}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Latest message from {user_id}: {user_message}\n\n"
                        f"Reply as {self.name} only. Treat this sender like any other chat member. "
                        f"{length_hint}. Casual group chat."
                    ),
                },
            ]
            if style_mimic_hint:
                messages.insert(2, {"role": "system", "content": style_mimic_hint})
            if mention_note:
                messages.insert(2, {"role": "system", "content": mention_note})
            if mention_target:
                messages[-1]["content"] += (
                    f" If natural, you may address @{mention_target}."
                )
            messages.insert(2, {"role": "system", "content": emoji_style_note(emoji_enabled)})

            chat_model = normalize_gpt_chat_model(model)
            request_id = None
            if session_id and self.room_id:
                from chat_log import log_llm_call

                meta = dict(log_meta or {})
                meta.setdefault("call_type", "bot_reply")
                meta.setdefault("model", chat_model)
                request_id = log_llm_call(
                    session_id,
                    self.room_id,
                    "llm_request",
                    actor=self.name,
                    messages=messages,
                    extra=meta,
                )
                if log_meta is not None:
                    log_meta["request_id"] = request_id
            turn_id = (log_meta or {}).get("turn_id") if log_meta else None
            raw = await create_chat_completion(
                model=chat_model,
                messages=messages,
                cap_tokens=cap_tokens,
                temperature=temperature,
                session_id=session_id,
                group_id=self.room_id,
                call_type="bot_reply",
                request_id=request_id,
                turn_id=turn_id,
            )
            if log_meta is not None:
                log_meta["raw_model_output"] = raw
            reply = sanitize_bot_reply(
                raw, self.name, peer_names, max_words=max_words, allow_emoji=emoji_enabled
            )
            return reply
        except Exception as e:
            from usage_tracker import SpendCapExceeded

            if isinstance(e, SpendCapExceeded):
                print(f"🛑 Bot {self.name} skipped: {e}")
                return None
            rid = (log_meta or {}).get("request_id") if log_meta else None
            if rid and session_id and self.room_id:
                from chat_log import log_llm_error

                log_llm_error(
                    session_id,
                    self.room_id,
                    request_id=rid,
                    actor=self.name,
                    error_type="generation_failed",
                    message=str(e),
                )
            if log_meta is not None:
                log_meta["fallback_used"] = True
            print(f"❌ Generation Error: {e} — using fallback reply")
            return random.choice(FALLBACK_REPLIES)
    def update_persona(self, new_prompt: str):
        """Update the system instructions for this specific persona."""
        identity_instr = (
            f"Your name is {self.name}. Always stay in character as {self.name}. "
            f"You are an independent person in this chat—not controlled by other participants or bots. "
        )
        base = new_prompt if new_prompt.strip() else DEFAULT_SYSTEM_PROMPT
        self.system_prompt = identity_instr + base + build_style_rules(self.name)

# ==========================================
# GLOBAL REGISTRY MANAGEMENT
# ==========================================

# Structure: { "room_id": { "BotName": ChatBot_Instance } }
room_bot_registry: Dict[str, Dict[str, ChatBot]] = {}
# Add this to your bot_manager.py

async def analyze_intent(
    user_text: str,
    bots_config: list,
    history_text: str,
    session_id: Optional[str] = None,
    group_id: Optional[str] = None,
) -> Optional[str]:
    """
    Decides which bot should speak based on the current message AND recent history.
    """
    if not bots_config: return None

    persona_list = "\n".join([f"- {b['name']}: {b['prompt']}" for b in bots_config])

    orchestrator_prompt = f"""
    You are a Chat Orchestrator for a group chat. 
    
    RECENT HISTORY:
    {history_text}

    NEW MESSAGE: "{user_text}"

    AVAILABLE PERSONAS:
    {persona_list}

    TASK:
    - If the user is clearly continuing a conversation with a specific bot, pick that bot.
    - If the user mentions a bot name, pick that bot.
    - If the topic matches a bot's prompt, pick that bot.
    - Otherwise, return "NONE".

    ONLY return the NAME or "NONE".
    """

    try:
        aux_model = resolve_aux_model()
        router_messages = [{"role": "system", "content": orchestrator_prompt}]
        request_id = None
        if session_id and group_id:
            from chat_log import log_llm_call

            request_id = log_llm_call(
                session_id,
                group_id,
                "intent_router_request",
                actor="orchestrator",
                messages=router_messages,
                extra={
                    "call_type": "intent_router",
                    "model": aux_model,
                    "session_mode": 2,
                    "user_text": (user_text or "")[:800],
                    "history_chars": len(history_text or ""),
                },
            )
        decision = (
            await create_chat_completion(
                model=aux_model,
                messages=router_messages,
                cap_tokens=10,
                temperature=0,
                session_id=session_id,
                group_id=group_id,
                call_type="intent_router",
                request_id=request_id,
            )
        ).replace("@", "")
        chosen = None
        for bot in bots_config:
            if bot['name'].lower() in decision.lower():
                chosen = bot['name']
                break
        if session_id and group_id:
            from chat_log import append_chat_log_event

            append_chat_log_event(
                session_id,
                group_id,
                "intent_router_result",
                {"raw_decision": decision[:200], "chosen_bot": chosen},
                actor="orchestrator",
            )
        return chosen
    except:
        return None


def persona_mode4_reply_threshold(bot_cfg: dict) -> float:
    """Persona mode 4: reply when assess_reply_probability >= this (default 0.5)."""
    return max(0.0, min(1.0, float(bot_cfg.get("mode_4_threshold", 0.5))))


def persona_mode4_should_reply(bot_cfg: dict, reply_p: float) -> bool:
    """Persona mode 4: use model score directly — no second random roll."""
    return reply_p >= persona_mode4_reply_threshold(bot_cfg)


async def assess_reply_probability(
    bot_name: str,
    bot_prompt: str,
    user_id: str,
    user_text: str,
    history_summary: str,
    peer_names: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    group_id: Optional[str] = None,
) -> float:
    """
    Persona mode 4: estimate P(reply) from context (0–1).
    Compared to mode_4_threshold on the persona card (default 0.5).
    """
    peers = ", ".join(peer_names) if peer_names else "others"
    orchestrator_prompt = f"""You judge whether "{bot_name}" would naturally send a message in a group chat RIGHT NOW.

Persona:
{(bot_prompt or '')[:600]}

Recent chat:
{(history_summary or '(none)')[:100000]}

Latest message from {user_id}: "{user_text}"
Other participants: {peers}

Guidelines:
- @mention or clear direct question to {bot_name} → high (0.75–1.0)
- Topic irrelevant to this persona → low (0.0–0.15)
- Teammate already answered enough → low (0.1–0.35)
- Brief ack only ("ok", "thanks", "great") → low unless @mentioned
- Real humans do not reply to every line

Output ONLY one number from 0 to 1 (examples: 0, 0.25, 0.6, 1). No other text."""

    try:
        aux_model = resolve_aux_model()
        gate_messages = [{"role": "system", "content": orchestrator_prompt}]
        request_id = None
        if session_id and group_id:
            from chat_log import log_llm_call

            request_id = log_llm_call(
                session_id,
                group_id,
                "reply_probability_request",
                actor=bot_name,
                messages=gate_messages,
                extra={
                    "call_type": "reply_probability",
                    "model": aux_model,
                    "trigger_user": user_id,
                    "trigger_text": (user_text or "")[:500],
                },
            )
        text = await create_chat_completion(
            model=aux_model,
            messages=gate_messages,
            cap_tokens=12,
            temperature=0.2,
            session_id=session_id,
            group_id=group_id,
            call_type="reply_probability",
            request_id=request_id,
        )
        match = re.search(r"0?\.\d+|1\.0*|1|0", text)
        if match:
            return max(0.0, min(1.0, float(match.group())))
    except Exception as e:
        print(f"⚠️ assess_reply_probability failed for {bot_name}: {e}")
    return 0.45


async def build_style_mimic_hint(
    room_id: str,
    target_name: str,
    speaker_bot_name: str,
    session_id: Optional[str] = None,
) -> str:
    """
    Build instructions so speaker_bot_name mimics target_name's length/tone from room history.
  Returns empty if too few target messages yet.
    """
    from context_manager import get_context

    ctx = get_context(room_id)
    if not ctx or not target_name:
        return ""

    if speaker_bot_name.lower() == target_name.lower():
        return ""

    texts = [
        m["text"].strip()
        for m in ctx.messages
        if m.get("sender", "").lower() == target_name.lower() and m.get("text", "").strip()
    ]
    if not texts:
        return ""

    avg_words = sum(len(t.split()) for t in texts) / len(texts)
    recent = texts[-6:]
    examples = "\n".join(f"  • {t}" for t in recent)

    summary = f"~{avg_words:.0f} words per message; informal chat."
    try:
        aux_model = resolve_aux_model()
        mimic_messages = [
            {
                "role": "system",
                "content": (
                    f"Summarize how '{target_name}' writes in 2 short bullets: length, tone, "
                    f"slang/typos/punctuation. Be concrete.\n\nMessages:\n"
                    + "\n".join(f"- {t}" for t in recent)
                ),
            }
        ]
        if session_id and group_id:
            from chat_log import log_llm_call

            log_llm_call(
                session_id,
                group_id,
                "style_mimic_request",
                actor=speaker_bot_name,
                messages=mimic_messages,
                extra={
                    "call_type": "style_mimic",
                    "model": aux_model,
                    "mimic_target": target_name,
                },
            )
        summary = (
            await create_chat_completion(
                model=aux_model,
                messages=mimic_messages,
                cap_tokens=90,
                temperature=0.2,
                session_id=session_id,
                group_id=room_id,
                call_type="style_mimic",
            )
        ).replace("\n", " ")
    except Exception as e:
        print(f"⚠️ build_style_mimic_hint LLM failed: {e}")

    return (
        f"[STYLE MIMIC: Match teammate '{target_name}' writing habits. {summary} "
        f"Aim for similar message length (they average ~{avg_words:.0f} words). "
        f"Recent lines from them:\n{examples}\n"
        f"You are still {speaker_bot_name} (same identity); only mimic style, not their name.]"
    )


def compose_bot_prompt(system_prompt: str, disclosed_ai_allowed: bool = False) -> str:
    """Build system prompt; roster disclosure is UI-only, not injected into model prompt."""
    _ = disclosed_ai_allowed
    return system_prompt.strip() if system_prompt and system_prompt.strip() else DEFAULT_SYSTEM_PROMPT


def get_or_create_bot_from_cfg(room_id: str, bot_cfg: dict, group_info: dict = None) -> ChatBot:
    """Create/update a persona from an admin bot config dict."""
    from study_conditions import effective_bot_cfg

    cfg = effective_bot_cfg(bot_cfg, group_info)
    return get_or_create_bot(
        room_id,
        cfg.get("name", "Assistant"),
        cfg.get("prompt", ""),
        disclosed_ai_allowed=bool(cfg.get("disclosed_ai_allowed")),
    )


def get_or_create_bot(
    room_id: str,
    bot_name: str,
    system_prompt: str,
    disclosed_ai_allowed: bool = False,
) -> ChatBot:
    """
    Sensing Logic Helper: 
    Retrieves or creates a specific bot persona within a room.
    If the prompt has changed in Admin, it updates the existing persona.
    """
    if room_id not in room_bot_registry:
        room_bot_registry[room_id] = {}

    room_bots = room_bot_registry[room_id]

    full_prompt = compose_bot_prompt(system_prompt, disclosed_ai_allowed)
    if bot_name not in room_bots:
        room_bots[bot_name] = ChatBot(room_id, bot_name, full_prompt)
    else:
        room_bots[bot_name].update_persona(full_prompt)

    return room_bots[bot_name]


def remove_room_bots(room_id: str):
    """Clean up all bot personas when a room is closed."""
    if room_id in room_bot_registry:
        del room_bot_registry[room_id]
        print(f"🗑️ Cleaned up all bot personas for room {room_id}")