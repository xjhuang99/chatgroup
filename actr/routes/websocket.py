import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from actr.ai_service import process_ai_logic
from actr.chat_context import hydrate_room_context_from_db
from actr.deps import group_locks, touch_group_activity
from actr.group_chat import ai_opening_wrapper, broadcast
from bot_queue import bot_response_queue
from group_lifecycle import shutdown_group_chat
from error_handler import error_handler
from group_idle import cancel_group_idle_timer
from match_manager import match_manager
from bot_interaction import all_peer_names, parse_at_mentions
from chat_log import log_participant_join
from session_runtime import (
    advance_turn,
    broadcast_turn,
    cancel_turn_timer,
    can_human_speak,
    init_turn_state,
    maybe_trigger_ai_opening,
    schedule_timed_turn,
)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/chat/{session_id}/{group_id}/{uid}")
async def websocket_chat(websocket: WebSocket, session_id: str, group_id: str, uid: str):
    session = match_manager.get_session(session_id)
    if not session:
        await websocket.close(code=1008, reason="Session not found")
        return

    allowed, err_msg = match_manager.can_websocket_join(session_id, group_id, uid)
    if not allowed:
        await websocket.accept()
        await websocket.send_text(json.dumps({"type": "error", "message": err_msg}))
        await websocket.close(code=4004, reason=err_msg[:123])
        return

    group_info = match_manager.get_group_info(session_id, group_id)
    await websocket.accept()
    await hydrate_room_context_from_db(session_id, group_id)

    if "ws_connections" not in group_info:
        group_info["ws_connections"] = []
    if "connections" not in group_info:
        group_info["connections"] = []

    if "member_names" not in group_info:
        group_info["member_names"] = {}

    if uid not in group_info["member_names"]:
        assigned_names = set(group_info["member_names"].values())
        available_names = [name for name in session.participant_names if name not in assigned_names]
        group_info["member_names"][uid] = available_names[0] if available_names else uid

    if uid not in group_info["members"]:
        group_info["members"].append(uid)

    match_manager.record_participant_group(session_id, uid, group_id)
    group_info["ws_connections"].append(websocket)
    group_info["connections"].append({"websocket": websocket, "uid": uid})
    touch_group_activity(session_id, group_id)
    display_name = group_info["member_names"][uid]
    log_participant_join(
        session_id,
        group_id,
        uid=uid,
        display_name=display_name,
        member_names=dict(group_info.get("member_names", {})),
    )

    init_turn_state(session, group_info)
    if session.turn_mode == "timed" and group_info.get("turn_initialized"):
        schedule_timed_turn(session_id, group_id, broadcast, session.turn_duration_seconds)
    await websocket.send_text(json.dumps({"type": "display_name", "name": display_name}))
    await broadcast_turn(session_id, group_id, broadcast)
    asyncio.create_task(
        maybe_trigger_ai_opening(session_id, group_id, broadcast, ai_opening_wrapper)
    )
    print(f"📡 {uid} ({display_name}) connected to {group_id} (Session: {session_id})")

    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip():
                continue

            try:
                control = json.loads(data)
                if isinstance(control, dict) and control.get("type") == "get_display_name":
                    display_name = group_info["member_names"].get(uid, uid)
                    await websocket.send_text(
                        json.dumps({"type": "display_name", "name": display_name})
                    )
                    continue
                if isinstance(control, dict) and control.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                    continue
            except (json.JSONDecodeError, TypeError):
                pass

            display_name = group_info["member_names"].get(uid, uid)

            if group_info.get("paused"):
                await websocket.send_text(
                    json.dumps({
                        "type": "error",
                        "message": "Chat is paused by the researcher.",
                    })
                )
                continue

            if not can_human_speak(display_name, session, group_info):
                order = group_info.get("turn_order", [])
                idx = group_info.get("turn_index", 0) % max(len(order), 1)
                current = order[idx] if order else "another participant"
                await websocket.send_text(
                    json.dumps({
                        "type": "turn_denied",
                        "message": f"Please wait — it is {current}'s turn.",
                        "current_speaker": current,
                    })
                )
                continue

            touch_group_activity(session_id, group_id)
            other_conns = [
                e["websocket"]
                for e in group_info.get("connections", [])
                if e.get("websocket") is not websocket
            ]
            mention_names = parse_at_mentions(
                data, all_peer_names(session, group_info)
            )
            msg_payload = json.dumps({
                "type": "message",
                "sender": display_name,
                "text": data,
                "mentions": mention_names,
            })
            await asyncio.gather(
                *[c.send_text(msg_payload) for c in other_conns],
                return_exceptions=True,
            )

            if session.turn_mode != "none":
                await advance_turn(session_id, group_id, broadcast)

            asyncio.create_task(process_ai_logic(session_id, group_id, display_name, data))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        error_handler.handle_exception(e, "websocket_endpoint")
    finally:
        group_info["connections"] = [
            e for e in group_info.get("connections", []) if e.get("websocket") is not websocket
        ]
        conns = group_info.get("ws_connections", [])
        if websocket in conns:
            conns.remove(websocket)

        if not group_info.get("connections") and not conns:
            cancel_turn_timer(session_id, group_id)
            cancel_group_idle_timer(session_id, group_id)
            if group_id in group_locks:
                del group_locks[group_id]
            bot_response_queue.cancel_room(group_id)
            from bot_manager import remove_room_bots

            remove_room_bots(group_id)

        print(f"🚪 {uid} disconnected from {group_id}")
