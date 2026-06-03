from fastapi import APIRouter, HTTPException, Query

from db.database import get_room_history
from match_manager import match_manager

router = APIRouter(tags=["groups"])


@router.get("/api/groups/{session_id}/{group_id}/info")
async def get_group_info_api(session_id: str, group_id: str):
    group_info = match_manager.get_group_info(session_id, group_id)
    if not group_info:
        return {"member_names": {}, "members": []}
    return {
        "member_names": group_info.get("member_names", {}),
        "members": group_info.get("members", []),
    }


@router.get("/api/groups/{session_id}/{group_id}/messages")
async def get_group_messages_api(
    session_id: str,
    group_id: str,
    participant_id: str = Query(...),
):
    if not match_manager.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    if not match_manager.participant_can_access_group(session_id, group_id, participant_id):
        raise HTTPException(status_code=403, detail="Not allowed to view this group chat")
    session = match_manager.get_session(session_id)
    limit = match_manager.resolve_history_limit(session)
    rows = await get_room_history(group_id, limit=limit)
    messages = [
        {
            "sender": m.get("sender", ""),
            "text": m.get("text", ""),
            "timestamp": m.get("timestamp", ""),
        }
        for m in rows
    ]
    return {"group_id": group_id, "messages": messages}
