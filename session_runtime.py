"""
Runtime helpers: turn-taking, AI opening, Qualtrics session end, participant export.
"""

import asyncio
import json
import random
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set

from match_manager import match_manager, SessionConfig, MatchManager
from context_manager import get_or_create_context, get_context
from bot_manager import get_or_create_bot_from_cfg
from db.database import get_room_history, save_message
from cache_manager import cache_manager
from activity_logger import activity_logger
from human_defaults import HUMAN_LIKE_SESSION
from chat_log import log_ai_opening, log_session_ended

turn_timer_tasks: Dict[str, asyncio.Task] = {}
_opening_locks: Dict[str, asyncio.Lock] = {}


def get_bot_names(session: SessionConfig) -> Set[str]:
    return {b.get("name", "").strip() for b in (session.bots or []) if b.get("name")}


def get_human_display_names(session: SessionConfig, group_info: Dict) -> List[str]:
    """Display names for matched humans (group members are always human participant IDs)."""
    names = []
    for uid in group_info.get("members", []):
        dn = group_info.get("member_names", {}).get(uid, uid)
        names.append(dn)
    return names


def turn_payload(session: SessionConfig, group_info: Dict) -> Dict:
    mode = session.turn_mode
    if mode == "none":
        return {"type": "turn_update", "turn_mode": "none", "can_speak": True}
    order = group_info.get("turn_order", [])
    idx = group_info.get("turn_index", 0) % max(len(order), 1)
    current = order[idx] if order else None
    remaining = None
    if mode == "timed" and group_info.get("turn_deadline"):
        remaining = max(0, int(group_info["turn_deadline"] - datetime.now().timestamp()))
    return {
        "type": "turn_update",
        "turn_mode": mode,
        "current_speaker": current,
        "turn_order": order,
        "can_speak": True,
        "seconds_remaining": remaining,
    }


def can_human_speak(display_name: str, session: SessionConfig, group_info: Dict) -> bool:
    if session.turn_mode == "none":
        return True
    order = group_info.get("turn_order", [])
    if not order:
        return True
    idx = group_info.get("turn_index", 0) % len(order)
    return order[idx] == display_name


def init_turn_state(session: SessionConfig, group_info: Dict):
    if session.turn_mode == "none" or group_info.get("turn_initialized"):
        return
    humans = get_human_display_names(session, group_info)
    if not humans:
        return
    group_info["turn_order"] = humans
    group_info["turn_index"] = 0
    group_info["turn_initialized"] = True
    if session.turn_mode == "timed":
        group_info["turn_deadline"] = datetime.now().timestamp() + session.turn_duration_seconds


def _iter_connections(group_info: Dict):
    for entry in group_info.get("connections", []):
        ws = entry.get("websocket")
        uid = entry.get("uid")
        if ws is not None and uid:
            yield uid, ws
    for ws in group_info.get("ws_connections", []):
        yield None, ws


async def broadcast_turn(session_id: str, group_id: str, broadcast_fn: Callable):
    session = match_manager.get_session(session_id)
    group_info = match_manager.get_group_info(session_id, group_id)
    if not session or not group_info:
        return
    base = turn_payload(session, group_info)
    order = group_info.get("turn_order", [])
    idx = group_info.get("turn_index", 0) % max(len(order), 1)
    current = order[idx] if order else None
    names = group_info.get("member_names", {})
    for uid, conn in _iter_connections(group_info):
        dn = names.get(uid, uid) if uid else None
        can = base["turn_mode"] == "none" or (dn and dn == current)
        p = {**base, "can_speak": can}
        try:
            await conn.send_text(json.dumps(p))
        except Exception:
            pass


async def advance_turn(session_id: str, group_id: str, broadcast_fn: Callable):
    session = match_manager.get_session(session_id)
    group_info = match_manager.get_group_info(session_id, group_id)
    if not session or not group_info or session.turn_mode == "none":
        return
    order = group_info.get("turn_order", [])
    if not order:
        return
    group_info["turn_index"] = (group_info.get("turn_index", 0) + 1) % len(order)
    if session.turn_mode == "timed":
        group_info["turn_deadline"] = datetime.now().timestamp() + session.turn_duration_seconds
        schedule_timed_turn(session_id, group_id, broadcast_fn, session.turn_duration_seconds)
    await broadcast_turn(session_id, group_id, broadcast_fn)


def schedule_timed_turn(session_id: str, group_id: str, broadcast_fn: Callable, seconds: int):
    key = f"{session_id}_{group_id}"
    if key in turn_timer_tasks:
        t = turn_timer_tasks.pop(key)
        if not t.done():
            t.cancel()

    async def _tick():
        try:
            await asyncio.sleep(seconds)
            await advance_turn(session_id, group_id, broadcast_fn)
        except asyncio.CancelledError:
            pass

    turn_timer_tasks[key] = asyncio.create_task(_tick())


def cancel_turn_timer(session_id: str, group_id: str):
    key = f"{session_id}_{group_id}"
    if key in turn_timer_tasks:
        t = turn_timer_tasks.pop(key)
        if not t.done():
            t.cancel()


async def build_transcript_text(group_id: str) -> str:
    messages = await get_room_history(group_id, limit=5000)
    lines = []
    for m in messages:
        ts = m.get("timestamp", "")
        lines.append(f"[{ts}] {m.get('sender', '?')}: {m.get('text', '')}")
        note = (m.get("note") or "").strip()
        if note:
            lines.append(f"           {note}")
    return "\n".join(lines)


def _parse_group_started_at(group_info: dict):
    started = group_info.get("created_at") if group_info else None
    if not started:
        return None
    if isinstance(started, datetime):
        return started
    try:
        return datetime.fromisoformat(str(started).replace("Z", "+00:00").replace("+00:00", ""))
    except (TypeError, ValueError):
        return None


def _count_participant_messages(messages: list, display_name: str, participant_id: str) -> int:
    n = 0
    for m in messages:
        sender = m.get("sender", "")
        if sender == display_name or sender == participant_id:
            n += 1
    return n


def compute_chat_status(
    session,
    group_info: Optional[dict],
    participant_id: str,
    export: Dict,
    handoff_reason: str = "unknown",
) -> Dict[str, str]:
    """
    Qualtrics chat_status codes:
      completed_full — group ran full scheduled duration
      left_early       — participant left before group timer ended
      no_messages      — connected but sent no messages
      never_joined     — never matched to a group
    """
    group_id = export.get("group_id")
    messages = export.get("messages") or []
    display_name = export.get("display_name") or participant_id
    human_msgs = _count_participant_messages(messages, display_name, participant_id)
    chat_min = getattr(session, "group_chat_duration_minutes", 5) or 5

    early_leave_reasons = (
        "qualtrics_next_click",
        "qualtrics_unload",
        "qualtrics_next",
        "page_unload",
        "ws_close",
        "pagehide",
    )

    if not group_id:
        return {
            "chat_status": "never_joined",
            "chat_status_detail": "Never matched to a chat group.",
        }

    # Group ended or server restarted: participant_index + DB still have transcript.
    if not group_info:
        if handoff_reason in ("duration_limit", "session_ended"):
            detail = f"Group chat completed (~{chat_min} min scheduled)."
            if human_msgs == 0:
                return {
                    "chat_status": "completed_full",
                    "chat_status_detail": detail + " Participant sent no messages.",
                }
            return {"chat_status": "completed_full", "chat_status_detail": detail}
        if human_msgs == 0:
            return {
                "chat_status": "no_messages",
                "chat_status_detail": "Joined a chat group but sent no messages.",
            }
        if handoff_reason in early_leave_reasons:
            return {
                "chat_status": "left_early",
                "chat_status_detail": (
                    f"Left before chat ended. Participant sent {human_msgs} message(s)."
                ),
            }
        return {
            "chat_status": "completed_full",
            "chat_status_detail": "Chat ended. Transcript preserved.",
        }

    planned_sec = max(60, int(chat_min) * 60)
    started = _parse_group_started_at(group_info)
    elapsed_sec = int((datetime.now() - started).total_seconds()) if started else 0
    group_timer_done = elapsed_sec >= planned_sec if started else False

    if handoff_reason in ("duration_limit", "session_ended") or group_timer_done:
        detail = f"Group chat completed (~{chat_min} min scheduled)."
        if human_msgs == 0:
            return {
                "chat_status": "completed_full",
                "chat_status_detail": detail + " Participant sent no messages.",
            }
        return {"chat_status": "completed_full", "chat_status_detail": detail}

    if human_msgs == 0:
        detail = (
            f"Left before chat ended (~{max(0, planned_sec - elapsed_sec) // 60} min remaining). "
            "No messages sent."
        )
        if handoff_reason in early_leave_reasons:
            detail = f"Clicked Next or left chat without sending messages. {detail}"
        return {"chat_status": "no_messages", "chat_status_detail": detail}

    return {
        "chat_status": "left_early",
        "chat_status_detail": (
            f"Left before chat ended (~{max(0, planned_sec - elapsed_sec) // 60} min remaining). "
            f"Participant sent {human_msgs} message(s)."
        ),
    }


async def build_participant_export(session_id: str, participant_id: str) -> Dict:
    from chat_log import build_research_chat_log_text, resolve_qualtrics_export_text

    group_id = match_manager.get_participant_group_id(session_id, participant_id)
    session = match_manager.get_session(session_id)
    if not group_id:
        return {
            "session_id": session_id,
            "participant_id": participant_id,
            "group_id": None,
            "messages": [],
            "transcript_text": "",
            "research_log_text": "",
            "qualtrics_export_text": "",
            "qualtrics_log_mode": getattr(session, "qualtrics_log_mode", "transcript") if session else "transcript",
        }
    messages = await get_room_history(group_id, limit=5000)
    group_info = match_manager.get_group_info(session_id, group_id) or {}
    display_name = group_info.get("member_names", {}).get(participant_id, participant_id)
    transcript_text = await build_transcript_text(group_id)
    research_log_text = await build_research_chat_log_text(group_id, messages=messages)
    qualtrics_export_text = resolve_qualtrics_export_text(
        session, transcript_text, research_log_text
    )
    return {
        "session_id": session_id,
        "participant_id": participant_id,
        "group_id": group_id,
        "display_name": display_name,
        "messages": messages,
        "transcript_text": transcript_text,
        "research_log_text": research_log_text,
        "qualtrics_export_text": qualtrics_export_text,
        "qualtrics_log_mode": getattr(session, "qualtrics_log_mode", "transcript") if session else "transcript",
    }


async def notify_session_ended(session_id: str, group_id: str, reason: str):
    """Send session_ended to each connection (personalized transcript when enabled)."""
    from group_idle import shutdown_group_idle

    shutdown_group_idle(match_manager, session_id, group_id)
    session = match_manager.get_session(session_id)
    group_info = match_manager.get_group_info(session_id, group_id) or {}
    cancel_turn_timer(session_id, group_id)

    duration_seconds = None
    started = _parse_group_started_at(group_info)
    if started:
        duration_seconds = max(0.0, (datetime.now() - started).total_seconds())
    log_session_ended(
        session_id,
        group_id,
        reason=reason,
        duration_seconds=duration_seconds,
        extra={
            "members": list(group_info.get("members", [])),
            "member_names": dict(group_info.get("member_names", {})),
        },
    )

    base = {
        "type": "session_ended",
        "reason": reason,
        "message": "This chat session has ended.",
        "qualtrics_handoff": bool(session and session.qualtrics_handoff_enabled),
        "qualtrics_store_chat": bool(session and session.qualtrics_store_chat),
        "qualtrics_field_transcript": getattr(session, "qualtrics_field_transcript", "transcript"),
        "qualtrics_field_status": getattr(session, "qualtrics_field_status", "chat_status"),
        "chat_status": "completed_full",
        "chat_status_detail": "",
    }
    if session:
        base["chat_status_detail"] = (
            f"Group chat completed (~{session.group_chat_duration_minutes} min scheduled)."
        )

    sent = set()
    for uid, conn in _iter_connections(group_info):
        if id(conn) in sent:
            continue
        sent.add(id(conn))
        payload = {**base, "participant_id": uid}
        if session and session.qualtrics_store_chat and uid:
            export = await build_participant_export(session_id, uid)
            payload["transcript_text"] = export.get(
                "qualtrics_export_text", export.get("transcript_text", "")
            )
            payload["transcript_json"] = json.dumps(export.get("messages", []))
            payload["qualtrics_log_mode"] = export.get("qualtrics_log_mode", "transcript")
            status = compute_chat_status(session, group_info, uid, export, reason or "session_ended")
            payload["chat_status"] = status["chat_status"]
            payload["chat_status_detail"] = status["chat_status_detail"]
        try:
            await conn.send_text(json.dumps(payload))
        except Exception:
            pass


async def maybe_trigger_ai_opening(
    session_id: str,
    group_id: str,
    broadcast_fn: Callable,
    process_opening_fn: Callable,
):
    """First WebSocket connect + empty history → optional AI opener (mutex per group)."""
    key = f"{session_id}_{group_id}"
    if key not in _opening_locks:
        _opening_locks[key] = asyncio.Lock()

    async with _opening_locks[key]:
        session = match_manager.get_session(session_id)
        group_info = match_manager.get_group_info(session_id, group_id)
        if not session or not group_info:
            return
        if not session.ai_starts_conversation or not session.bot_enabled or not session.bots:
            return
        if group_info.get("opening_sent"):
            return
        history = await get_room_history(group_id, limit=1)
        if history:
            group_info["opening_sent"] = True
            return

        group_info["opening_sent"] = True
        bot_cfg = random.choice(session.bots)
        bot_name = bot_cfg.get("name", "Assistant")
        await process_opening_fn(session_id, group_id, bot_cfg, bot_name)


async def send_ai_opening_message(session_id: str, group_id: str, bot_cfg: Dict, bot_name: str, broadcast_fn: Callable):
    session = match_manager.get_session(session_id)
    limit = MatchManager.resolve_history_limit(session)
    get_or_create_context(group_id, max_messages=limit)
    ctx = get_context(group_id)
    group_info = match_manager.get_group_info(session_id, group_id) or {}
    bot = get_or_create_bot_from_cfg(group_id, bot_cfg, group_info)

    hs = HUMAN_LIKE_SESSION
    opening_delay = float(
        getattr(session, "opening_delay_seconds", None)
        if session and getattr(session, "opening_delay_seconds", None) is not None
        else hs.get("opening_delay_seconds", 2.0)
    )
    default_text = (
        (getattr(session, "default_opening_text", None) or "").strip()
        if session
        else ""
    ) or str(hs.get("default_opening_text", "hi")).strip() or "hi"

    await asyncio.sleep(max(0.0, opening_delay))
    reply = default_text
    log_ai_opening(
        session_id,
        group_id,
        bot_name=bot.name,
        text=reply,
        delay_seconds=opening_delay,
    )
    cache_manager.cache_message(group_id, bot.name, reply)
    await save_message(group_id, bot.name, reply)
    if ctx:
        ctx.add_message(bot.name, reply)
    activity_logger.log_bot_response(session_id, group_id, bot.name, reply, bot_cfg.get("mode", 1))
    await broadcast_fn(session_id, group_id, {"type": "message", "sender": bot.name, "text": reply})
    return bot.name, reply
