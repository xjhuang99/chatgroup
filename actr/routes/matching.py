from typing import Optional

from fastapi import APIRouter, Query

from match_manager import match_manager, resolve_human_group_bounds

router = APIRouter(tags=["matching"])


@router.get("/api/match")
async def match_user(
    session_id: str = Query(...),
    uid: str = Query(...),
    condition: Optional[str] = Query(None),
):
    if uid in match_manager.user_locations:
        loc = match_manager.user_locations[uid]
        if loc.get("session_id") == session_id:
            return {
                "status": "matched",
                "session_id": session_id,
                "group_id": loc["group_id"],
            }
    session = match_manager.get_session(session_id)
    if not session:
        return {
            "status": "session_not_found",
            "message": "Session not found. Check the session_id from your researcher.",
            "session_id": session_id,
        }
    if not match_manager.is_session_open(session):
        return {
            "status": "session_closed",
            "message": "This study session is no longer accepting participants.",
            "session_id": session_id,
        }
    match_condition = condition
    if session and not getattr(session, "condition_enabled", True):
        match_condition = None
    group_id = match_manager.add_to_queue(session_id, uid, condition=match_condition)
    if group_id:
        return {"status": "matched", "session_id": session_id, "group_id": group_id}
    session = match_manager.get_session(session_id)
    mode = session.assignment_mode if session else "fifo"
    resp_condition = (
        (condition or "_default") if (session and getattr(session, "condition_enabled", True)) else None
    )
    min_h, max_h = resolve_human_group_bounds(session)
    return {
        "status": "waiting",
        "assignment_mode": mode,
        "condition": resp_condition,
        "min_humans_per_group": min_h,
        "max_humans_per_group": max_h,
        "fixed_human_group_size": min_h == max_h,
    }


@router.get("/api/embed/status")
async def embed_participant_status(
    session_id: str = Query(...),
    participant_id: str = Query(...),
):
    if participant_id in match_manager.user_locations:
        loc = match_manager.user_locations[participant_id]
        if loc.get("session_id") == session_id:
            return {
                "status": "matched",
                "session_id": session_id,
                "group_id": loc["group_id"],
                "participant_id": participant_id,
            }
    if match_manager.is_user_in_queue(session_id, participant_id):
        return {"status": "waiting", "session_id": session_id, "participant_id": participant_id}
    return {"status": "not_joined", "session_id": session_id, "participant_id": participant_id}


@router.get("/api/leave")
async def leave_queue(
    session_id: str = Query(...),
    uid: str = Query(...),
    condition: Optional[str] = Query(None),
):
    match_manager.remove_from_queue(session_id, uid, condition=condition)
    return {"status": "ok"}
