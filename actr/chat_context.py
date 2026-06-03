"""In-memory chat context hydration from persistence."""

from context_manager import get_or_create_context
from db.database import get_room_history
from match_manager import match_manager


async def hydrate_room_context_from_db(session_id: str, group_id: str) -> None:
    """Load persisted messages into in-memory context (once per room)."""
    session = match_manager.get_session(session_id)
    limit = match_manager.resolve_history_limit(session)
    ctx = get_or_create_context(group_id, max_messages=limit)
    if ctx.messages:
        return
    rows = await get_room_history(group_id, limit=limit)
    for m in rows:
        ctx.add_message(
            m.get("sender", "?"),
            m.get("text", ""),
            m.get("timestamp"),
        )
