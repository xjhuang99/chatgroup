"""Group broadcast, duration timeout, and idle nudge timers."""

import asyncio
import json
import random
from datetime import datetime
from typing import Dict

from activity_logger import activity_logger
from bot_interaction import interaction_settings, schedule_bot_chain
from bot_manager import (
    compute_typing_delay_seconds,
    get_or_create_bot_from_cfg,
    resolve_chat_model,
)
from group_lifecycle import shutdown_group_chat
from cache_manager import cache_manager
from context_manager import get_context, resolve_context_max_chars
from db.database import save_message
from group_idle import (
    cancel_group_idle_timer,
    group_idle_tasks,
    is_group_chat_live,
    shutdown_group_idle,
)
from match_manager import match_manager
from session_runtime import notify_session_ended, send_ai_opening_message

from actr.deps import DEFAULT_IDLE_THRESHOLD, touch_group_activity


async def broadcast(session_id: str, group_id: str, payload) -> None:
    """Broadcasts a JSON message to all WebSocket connections in a group."""
    group_info = match_manager.get_group_info(session_id, group_id)
    if not group_info:
        return

    conns = group_info.get("ws_connections", [])
    if not conns:
        return

    message = json.dumps(payload) if isinstance(payload, dict) else str(payload)
    await asyncio.gather(
        *[conn.send_text(message) for conn in conns],
        return_exceptions=True,
    )


async def group_timeout_watcher() -> None:
    """Ends each group chat after group_chat_duration_minutes from group formation."""
    while True:
        await asyncio.sleep(15)
        now = datetime.now()
        for session_id, groups in list(match_manager.active_rooms.items()):
            session = match_manager.get_session(session_id)
            if not session:
                continue
            duration_seconds = max(1, session.group_chat_duration_minutes) * 60
            for group_id, group_info in list(groups.items()):
                started = group_info.get("created_at")
                if not started:
                    continue
                if isinstance(started, str):
                    try:
                        started = datetime.fromisoformat(started)
                    except ValueError:
                        continue
                if (now - started).total_seconds() >= duration_seconds:
                    shutdown_group_idle(match_manager, session_id, group_id)
                    await notify_session_ended(session_id, group_id, "duration_limit")
                    for entry in list(group_info.get("connections", [])):
                        try:
                            await entry["websocket"].close()
                        except Exception:
                            pass
                    for conn in list(group_info.get("ws_connections", [])):
                        try:
                            await conn.close()
                        except Exception:
                            pass
                    shutdown_group_chat(match_manager, session_id, group_id, end_group=True)
                    print(
                        f"⏱️ Group {group_id} closed after "
                        f"{session.group_chat_duration_minutes}m chat duration"
                    )


def reset_idle_timer(
    session_id: str, group_id: str, idle_seconds: int = DEFAULT_IDLE_THRESHOLD
) -> None:
    """Resets the idle timer for bot auto-initiation within a group."""
    if not is_group_chat_live(match_manager, session_id, group_id):
        return

    task_key = f"{session_id}_{group_id}"

    if task_key in group_idle_tasks:
        task = group_idle_tasks[task_key]
        if not task.done():
            task.cancel()

    async def idle_watcher():
        from actr.ai_service import process_ai_logic

        try:
            await asyncio.sleep(idle_seconds)
        except asyncio.CancelledError:
            return

        if not is_group_chat_live(match_manager, session_id, group_id):
            return
        from bot_queue import bot_response_queue

        if bot_response_queue.is_room_cancelled(group_id):
            return

        session_cfg = match_manager.get_session(session_id)
        if not session_cfg or not session_cfg.bot_enabled or not session_cfg.bots:
            return

        ctx = get_context(group_id)
        if not ctx:
            return

        initiator_cfg = random.choice(session_cfg.bots)
        gi = match_manager.get_group_info(session_id, group_id) or {}
        if not gi or gi.get("ended"):
            return
        initiator = get_or_create_bot_from_cfg(group_id, initiator_cfg, gi)
        summary = ctx.get_context_summary(
            max_chars=resolve_context_max_chars(initiator_cfg),
        )

        session_cfg = match_manager.get_session(session_id)
        peer_names = [
            b["name"]
            for b in (session_cfg.bots if session_cfg else [])
            if b.get("name") and b["name"] != initiator.name
        ]
        init_prompt = (
            "[Chat went quiet. Send ONE casual line (max 2 short sentences) "
            "to nudge the group—no lists, no 'hello team'.]"
        )
        reply = await initiator.generate_response(
            "system",
            init_prompt,
            summary,
            temperature=initiator_cfg.get("temperature", 0.7),
            peer_names=peer_names,
            max_words=initiator_cfg.get("max_words", 35),
            min_words=initiator_cfg.get("min_words", 1),
            length_variation=initiator_cfg.get("length_variation", True),
            max_tokens=initiator_cfg.get("max_tokens"),
            emoji_enabled=bool(initiator_cfg.get("emoji_enabled", False)),
            model=resolve_chat_model(initiator_cfg),
            session_id=session_id,
        )

        if reply:
            await asyncio.sleep(
                compute_typing_delay_seconds(reply, initiator_cfg.get("typing_cps", 4))
            )
            cache_manager.cache_message(group_id, initiator.name, reply)
            await save_message(group_id, initiator.name, reply)
            ctx.add_message(initiator.name, reply)
            activity_logger.log_bot_response(
                session_id, group_id, initiator.name, reply, initiator_cfg.get("mode", 1)
            )
            await broadcast(
                session_id, group_id, {"type": "message", "sender": initiator.name, "text": reply}
            )
            touch_group_activity(session_id, group_id)
            if is_group_chat_live(match_manager, session_id, group_id):
                settings = interaction_settings(session_cfg)
                schedule_bot_chain(
                    session_id,
                    group_id,
                    initiator.name,
                    reply,
                    0,
                    settings,
                    process_ai_logic,
                )

        if is_group_chat_live(match_manager, session_id, group_id):
            reset_idle_timer(
                session_id, group_id, initiator_cfg.get("idle_threshold", DEFAULT_IDLE_THRESHOLD)
            )

    group_idle_tasks[task_key] = asyncio.create_task(idle_watcher())


async def ai_opening_wrapper(
    session_id: str, group_id: str, bot_cfg: Dict, bot_name: str
) -> None:
    from actr.ai_service import process_ai_logic

    opener = await send_ai_opening_message(session_id, group_id, bot_cfg, bot_name, broadcast)
    if not opener:
        return
    opener_name, opener_text = opener
    session_cfg = match_manager.get_session(session_id)
    if not session_cfg:
        return
    settings = interaction_settings(session_cfg)
    schedule_bot_chain(
        session_id, group_id, opener_name, opener_text, 0, settings, process_ai_logic
    )
