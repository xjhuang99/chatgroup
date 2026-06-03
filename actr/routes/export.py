import csv
import json
from io import BytesIO, StringIO

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from activity_logger import activity_logger
from admin_auth import require_admin
from context_manager import resolve_context_max_chars
from db.database import get_room_history
from match_manager import match_manager

router = APIRouter(tags=["export"])


@router.get("/api/export/session/{session_id}/activity", dependencies=[Depends(require_admin)])
async def export_session_activity(session_id: str):
    buf = StringIO()
    writer = csv.writer(buf)

    session_cfg = match_manager.get_session(session_id)
    writer.writerow(["=== SESSION SETTINGS ==="])
    if session_cfg:
        writer.writerow(["Session ID", session_cfg.session_id])
        writer.writerow(["Session Name", getattr(session_cfg, "name", "")])
        writer.writerow(["Session Mode", session_cfg.session_mode])
        writer.writerow(["Bot Enabled", session_cfg.bot_enabled])
        writer.writerow(["Group Size", session_cfg.group_size])
        writer.writerow(["Survey Open (days)", getattr(session_cfg, "survey_open_days", "")])
        writer.writerow(
            ["Group Chat Duration (min)", getattr(session_cfg, "group_chat_duration_minutes", "")]
        )
        writer.writerow(["History Limit", getattr(session_cfg, "history_limit", "")])
        writer.writerow(
            ["Participant Names", ", ".join(getattr(session_cfg, "participant_names", []) or [])]
        )
        writer.writerow([])
        writer.writerow(["=== BOT CONFIGURATION ==="])
        writer.writerow(
            [
                "Bot Name",
                "Prompt",
                "Mode",
                "Delay (s)",
                "Max Tokens",
                "Temperature",
                "Typing CPS",
                "Context Max Chars",
                "Silence Timeout (s)",
                "Avatar Type",
            ]
        )
        for bot in session_cfg.bots or []:
            writer.writerow(
                [
                    bot.get("name", ""),
                    bot.get("prompt", ""),
                    bot.get("mode", 1),
                    bot.get("delay_seconds", 2),
                    bot.get("max_tokens", 200),
                    bot.get("temperature", 0.7),
                    bot.get("typing_cps", 4),
                    bot.get("context_max_chars", resolve_context_max_chars(bot)),
                    bot.get("idle_threshold", 20),
                    bot.get("avatar_type", "bot"),
                ]
            )
    else:
        writer.writerow(["Session not found", session_id])
    writer.writerow([])

    writer.writerow(["=== ACTIVITY LOG ==="])
    writer.writerow(["timestamp", "event_type", "session_id", "room_id", "actor", "details"])
    activities = activity_logger.get_session_activities(session_id)
    for a in activities:
        writer.writerow(
            [
                a.get("timestamp", ""),
                a.get("event_type", ""),
                a.get("session_id", ""),
                a.get("room_id", ""),
                a.get("actor", ""),
                json.dumps(a.get("details", {})),
            ]
        )

    output = BytesIO(buf.getvalue().encode("utf-8"))
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=activity_{session_id}.csv"},
    )


@router.get("/api/export/room/{room_id}/messages", dependencies=[Depends(require_admin)])
async def export_room_messages(room_id: str):
    messages = await get_room_history(room_id, limit=10000)
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "room_id", "sender", "message"])
    for m in messages:
        writer.writerow([
            m.get("timestamp", ""),
            room_id,
            m.get("sender", ""),
            m.get("text", ""),
        ])
    output = BytesIO(buf.getvalue().encode("utf-8"))
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=messages_{room_id}.csv"},
    )
