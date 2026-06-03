"""
Bot-to-bot chain triggers and optional mention/self-correction helpers.
"""

from __future__ import annotations

import asyncio
import random
import re
from typing import Dict, List, Optional, Set

from human_defaults import HUMAN_LIKE_SESSION


def interaction_settings(session=None) -> Dict:
    """Session-level orchestration (spacing uses each persona's delay_seconds)."""
    if session is None:
        session = type("_Defaults", (), {})()
    hs = HUMAN_LIKE_SESSION
    return {
        "bot_reply_on_any_message": bool(
            getattr(session, "bot_reply_on_any_message", hs["bot_reply_on_any_message"])
        ),
        "max_chain_depth": max(1, int(getattr(session, "max_chain_depth", hs["max_chain_depth"]))),
        "use_mentions": bool(getattr(session, "use_mentions", hs["use_mentions"])),
        "mention_prob": max(
            0.0, min(1.0, float(getattr(session, "mention_prob", hs["mention_prob"])))
        ),
        "self_correction_prob": max(
            0.0,
            min(1.0, float(getattr(session, "self_correction_prob", hs["self_correction_prob"]))),
        ),
    }


def bot_names(session) -> List[str]:
    if not session:
        return []
    return [b.get("name") for b in (session.bots or []) if b.get("name")]


def message_mentions_name(text: str, name: str, *, require_at: bool = False) -> bool:
    """True if message @-mentions name, or (mode 3) uses name as a whole word."""
    if not name or not text:
        return False
    if re.search(rf"@{re.escape(name)}\b", text, re.IGNORECASE):
        return True
    if require_at:
        return False
    return bool(re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE))


def parse_at_mentions(text: str, names: List[str]) -> List[str]:
    """Names explicitly @-mentioned in text (case-insensitive, word boundary)."""
    if not text or not names:
        return []
    found: List[str] = []
    for name in sorted(set(names), key=len, reverse=True):
        if re.search(rf"@{re.escape(name)}\b", text, re.IGNORECASE):
            found.append(name)
    return found


def all_peer_names(session, group_info=None, exclude: Optional[str] = None) -> List[str]:
    """Humans + bots in the room (for prompts and mentions)."""
    names: List[str] = []
    seen: Set[str] = set()
    if group_info:
        for n in (group_info.get("member_names") or {}).values():
            if n and n != exclude and n not in seen:
                seen.add(n)
                names.append(n)
    if session:
        for n in bot_names(session):
            if n != exclude and n not in seen:
                seen.add(n)
                names.append(n)
    return names


def pick_mention_target(
    latest_sender: str,
    latest_text: str,
    peers: List[str],
    settings: Dict,
) -> Optional[str]:
    if not settings.get("use_mentions"):
        return None
    if not peers:
        return None
    if random.random() > settings.get("mention_prob", 0.35):
        return None

    # Prefer @mention already in the triggering message
    for name in peers:
        if re.search(rf"@{re.escape(name)}\b", latest_text or "", re.IGNORECASE):
            return name

    # Otherwise pick someone other than self (can be human or bot)
    candidates = [p for p in peers if p.lower() != (latest_sender or "").lower()]
    if not candidates:
        candidates = list(peers)
    return random.choice(candidates)


def apply_mention_prefix(reply: str, target: Optional[str], settings: Dict) -> str:
    if not reply or not target or not settings.get("use_mentions"):
        return reply
    if re.search(rf"@{re.escape(target)}\b", reply, re.IGNORECASE):
        return reply
    # Light touch: only prefix sometimes so not every line has @
    if random.random() < 0.65:
        return reply
    return f"@{target} {reply}"


def build_mention_system_note(settings: Dict) -> str:
    if not settings.get("use_mentions"):
        return ""
    return (
        "You may address someone with @name when it feels natural. "
        "Treat every sender the same whether they are a person or another bot in the chat."
    )


async def maybe_self_correction(
    session_id: str,
    group_id: str,
    bot_name: str,
    original_reply: str,
    settings: Dict,
    broadcast_fn,
    save_message_fn,
    cache_message_fn,
    add_context_fn,
):
    """Lightweight 'edit': send a follow-up correction line after a short delay."""
    prob = settings.get("self_correction_prob", 0.12)
    if prob <= 0 or random.random() > prob:
        return

    await asyncio.sleep(random.uniform(2.0, 6.0))

    templates = [
        "*Let me rephrase that — {body}",
        "*Actually I meant: {body}",
        "*Quick fix on my last message: {body}",
    ]
    body = original_reply.strip()
    if len(body) > 120:
        body = body[:117] + "..."
    correction = random.choice(templates).format(body=body)

    await broadcast_fn(session_id, group_id, {"type": "message", "sender": bot_name, "text": correction})
    if cache_message_fn:
        cache_message_fn(group_id, bot_name, correction)
    if save_message_fn:
        await save_message_fn(group_id, bot_name, correction)
    if add_context_fn:
        add_context_fn(group_id, bot_name, correction)


def bots_for_message(session, message_text: str) -> List[Dict]:
    """Which bot personas may respond to this message (session_mode rules)."""
    bots = list(session.bots or []) if session else []
    if not bots:
        return []
    mode = int(getattr(session, "session_mode", HUMAN_LIKE_SESSION["session_mode"]) or 1)
    text = message_text or ""
    if mode == 3:
        return [
            b
            for b in bots
            if message_mentions_name(text, b.get("name") or "")
        ]
    # mode 1 / 4: all bots; mode 2 handled separately in main
    if mode == 2:
        return []
    return bots


def filter_bots_for_trigger(
    bot_list: List[Dict],
    trigger_sender: str,
) -> List[Dict]:
    """Do not let a bot reply to its own message (reduces chain spam)."""
    if not trigger_sender:
        return bot_list
    return [b for b in bot_list if b.get("name") != trigger_sender]


def schedule_bot_chain(
    session_id: str,
    group_id: str,
    sender_name: str,
    sender_text: str,
    chain_depth: int,
    settings: Dict,
    process_ai_logic_fn,
) -> None:
    """After any message (human or bot), optionally trigger another bot wave."""
    from group_idle import is_group_chat_live
    from match_manager import match_manager as mm

    hs = HUMAN_LIKE_SESSION
    if not is_group_chat_live(mm, session_id, group_id):
        return
    if not settings.get("bot_reply_on_any_message"):
        return
    max_depth = settings.get("max_chain_depth", hs["max_chain_depth"])
    if chain_depth >= max_depth:
        return

    asyncio.create_task(
        process_ai_logic_fn(
            session_id,
            group_id,
            sender_name,
            sender_text,
            chain_depth=chain_depth + 1,
            trigger_kind="bot",
        )
    )
