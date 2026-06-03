from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from admin_auth import is_super_admin, require_admin, require_auth, require_session_access
from cache_manager import cache_manager
from db.database import delete_room_data, get_room_history
from error_handler import error_handler
from group_lifecycle import shutdown_group_chat
from match_manager import match_manager
from usage_tracker import (
    get_group_spend_usd,
    get_group_usage,
    resolve_group_spend_cap,
)

router = APIRouter(tags=["admin"])


def _owner_filter(request: Request):
    principal = require_auth(request)
    return None if is_super_admin(principal) else principal.get("account_id")


def _require_room_access(request: Request, session_id: str) -> None:
    session = match_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    require_session_access(request, getattr(session, "owner_account_id", None))


def _require_group_room_access(request: Request, group_id: str) -> str:
    """Return session_id after ownership check (active or ended rooms)."""
    session_id = match_manager.resolve_session_id_for_group(group_id)
    if not session_id:
        raise HTTPException(status_code=404, detail="Room not found")
    _require_room_access(request, session_id)
    return session_id


@router.get("/api/admin/rooms", dependencies=[Depends(require_auth)])
async def admin_get_rooms(request: Request):
    owner = _owner_filter(request)
    rooms = []
    for session_summary in match_manager.get_all_sessions_summary(owner):
        sid = session_summary["id"]
        for group_id in session_summary.get("groups", []):
            group_info = match_manager.get_group_info(sid, group_id)
            if group_info:
                history = await get_room_history(group_id, limit=1000)
                cap = resolve_group_spend_cap(sid, group_id, group_info)
                spent = get_group_spend_usd(group_id)
                usage = get_group_usage(group_id)
                rooms.append({
                    "id": group_id,
                    "session_id": sid,
                    "session_name": session_summary["name"],
                    "created_at": group_info.get("created_at", datetime.now()).isoformat()
                    if hasattr(group_info.get("created_at"), "isoformat")
                    else str(group_info.get("created_at", "")),
                    "participants": group_info.get("members", []),
                    "message_count": len(history),
                    "api_spend_usd": round(spent, 4),
                    "api_spend_cap_usd": cap,
                    "api_calls": usage.get("api_calls", 0),
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "paused": bool(group_info.get("paused", False)),
                })

    summaries = match_manager.get_all_sessions_summary(owner)
    bot_enabled = any(
        match_manager.get_session(s["id"]).bot_enabled
        for s in summaries
        if match_manager.get_session(s["id"])
    )

    waiting_count = match_manager.count_waiting_participants()

    return {
        "rooms": rooms,
        "waiting_count": waiting_count,
        "bot_enabled": bot_enabled,
    }


@router.get("/api/admin/config", dependencies=[Depends(require_auth)])
async def admin_get_config(request: Request):
    owner = _owner_filter(request)
    for summary in match_manager.get_all_sessions_summary(owner):
        session = match_manager.get_session(summary["id"])
        if session and session.bot_enabled:
            return {"bots": session.bots, "bot_enabled": True}
    return {"bots": [], "bot_enabled": False}


@router.get("/api/admin/rooms/{room_id}/messages", dependencies=[Depends(require_auth)])
async def admin_get_room_messages(room_id: str, request: Request):
    _require_group_room_access(request, room_id)
    messages = await get_room_history(room_id, limit=200)
    return {"messages": messages}


@router.post("/api/admin/rooms/{room_id}/pause", dependencies=[Depends(require_auth)])
async def admin_pause_room(room_id: str, request: Request):
    try:
        for session_id, groups in match_manager.active_rooms.items():
            if room_id in groups:
                _require_group_room_access(request, room_id)
                groups[room_id]["paused"] = True
                return {"status": "success", "message": f"Room {room_id} paused", "paused": True}
        return {"status": "error", "message": "Room not found"}
    except Exception as e:
        error_id = error_handler.handle_exception(e, "admin_pause_room")
        return {"status": "error", "message": str(e), "error_id": error_id}


@router.post("/api/admin/rooms/{room_id}/unpause", dependencies=[Depends(require_auth)])
async def admin_unpause_room(room_id: str, request: Request):
    try:
        for session_id, groups in match_manager.active_rooms.items():
            if room_id in groups:
                _require_group_room_access(request, room_id)
                groups[room_id]["paused"] = False
                return {"status": "success", "message": f"Room {room_id} resumed", "paused": False}
        return {"status": "error", "message": "Room not found"}
    except Exception as e:
        error_id = error_handler.handle_exception(e, "admin_unpause_room")
        return {"status": "error", "message": str(e), "error_id": error_id}


@router.delete("/api/admin/rooms/{room_id}", dependencies=[Depends(require_auth)])
async def admin_delete_room(room_id: str, request: Request):
    try:
        for session_id, groups in match_manager.active_rooms.items():
            if room_id in groups:
                _require_group_room_access(request, room_id)
                shutdown_group_chat(match_manager, session_id, room_id, end_group=True)
                await delete_room_data(room_id)
                cache_manager.invalidate_summary(room_id)
                return {"status": "success", "message": f"Room {room_id} deleted"}
        return {"status": "error", "message": "Room not found"}
    except Exception as e:
        error_id = error_handler.handle_exception(e, "admin_delete_room")
        return {"status": "error", "message": str(e), "error_id": error_id}


@router.delete("/api/admin/sessions/{session_id}", dependencies=[Depends(require_admin)])
async def admin_delete_session(session_id: str):
    try:
        if session_id not in match_manager.sessions:
            return {"status": "error", "message": "Session not found"}

        if session_id in match_manager.active_rooms:
            for group_id in list(match_manager.active_rooms[session_id].keys()):
                shutdown_group_chat(match_manager, session_id, group_id, end_group=True)
                await delete_room_data(group_id)
                cache_manager.invalidate_summary(group_id)

        del match_manager.sessions[session_id]
        if session_id in match_manager.active_rooms:
            del match_manager.active_rooms[session_id]
        if session_id in match_manager.forming_fifo:
            del match_manager.forming_fifo[session_id]
        if session_id in match_manager.forming_stratified:
            del match_manager.forming_stratified[session_id]
        if session_id in match_manager.participant_groups:
            del match_manager.participant_groups[session_id]
            match_manager.save_participant_index()
        for uid, loc in list(match_manager.user_locations.items()):
            if loc.get("session_id") == session_id:
                del match_manager.user_locations[uid]

        match_manager.save_all_sessions()
        return {"status": "success", "message": f"Session {session_id} deleted"}
    except Exception as e:
        error_id = error_handler.handle_exception(e, "admin_delete_session")
        return {"status": "error", "message": str(e), "error_id": error_id}
