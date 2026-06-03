"""Per-room context version for session mode 4 (parallel bots, refresh on peer messages)."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from cache_manager import cache_manager
from context_manager import get_context
from db.database import save_message


def init_room_context_state(group_info: Dict) -> None:
    group_info.setdefault("context_version", 0)
    group_info.setdefault("last_context_bump_sender", None)
    group_info.setdefault("last_context_bump_text", "")


def get_context_version(group_info: Dict) -> int:
    return int(group_info.get("context_version", 0) or 0)


def is_context_stale(group_info: Dict, version_at_start: int, bot_name: str) -> bool:
    """Stale only when someone other than this bot committed since version_at_start."""
    current = get_context_version(group_info)
    if current <= version_at_start:
        return False
    return (group_info.get("last_context_bump_sender") or "") != bot_name


def refresh_user_text_suffix(group_info: Dict, attempt: int) -> str:
    """Extra user message for LLM on refresh attempts (attempt >= 1)."""
    if attempt < 1:
        return ""
    who = group_info.get("last_context_bump_sender") or "someone"
    snippet = (group_info.get("last_context_bump_text") or "").strip()
    if len(snippet) > 200:
        snippet = snippet[:200] + "…"
    return (
        f'[Someone just said: "{snippet}". '
        f"One short reaction only, don't repeat your earlier draft.]"
    )


def transcript_note_for_refresh(
    attempt: int,
    peer_sender: str,
    peer_text: str,
) -> str:
    snippet = (peer_text or "").strip()
    if len(snippet) > 120:
        snippet = snippet[:120] + "…"
    return (
        f"[mode4 refresh attempt {attempt + 1}; reacted to {peer_sender}: "
        f'"{snippet}"; prompt suffix applied]'
    )


async def commit_room_message(
    group_id: str,
    sender: str,
    text: str,
    group_info: Dict,
    *,
    note: Optional[str] = None,
    bump_for_peers: bool = True,
    session_id: Optional[str] = None,
) -> None:
    """
    Persist message, update in-memory context, and optionally bump version for peer bots.
    bump_for_peers: when True, increment context_version (mode 4 peers treat as stale).
    """
    init_room_context_state(group_info)
    await save_message(group_id, sender, text, note=note)
    ctx = get_context(group_id)
    if ctx:
        ctx.add_message(sender, text)
        cache_manager.invalidate_summary(group_id)

    if bump_for_peers:
        group_info["context_version"] = get_context_version(group_info) + 1
        group_info["last_context_bump_sender"] = sender
        group_info["last_context_bump_text"] = text or ""
        if session_id:
            from chat_log import log_context_bump

            log_context_bump(
                session_id,
                group_id,
                context_version=get_context_version(group_info),
                sender=sender,
                text_preview=text or "",
            )


def mode4_settings(session_cfg) -> Tuple[float, float, int]:
    jitter = float(getattr(session_cfg, "parallel_start_jitter_sec", 1.5) or 0)
    rethink = float(getattr(session_cfg, "rethink_seconds", 2.0) or 2.0)
    attempts = int(getattr(session_cfg, "max_refresh_attempts", 2) or 2)
    return max(0.0, min(jitter, 30.0)), max(0.0, min(rethink, 30.0)), max(1, min(attempts, 10))


def is_parallel_session(session_cfg) -> bool:
    return int(getattr(session_cfg, "session_mode", 1) or 1) == 4
