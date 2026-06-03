from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from actr.schemas import EmbedHandoffRequest, SessionCreateRequest, SessionUpdateRequest
from activity_logger import activity_logger
from admin_auth import is_super_admin, require_admin, require_auth, require_session_access
from error_handler import error_handler
from human_defaults import GPT_CHAT_MODELS, normalize_gpt_chat_model
from match_manager import match_manager, resolve_human_group_bounds
from session_runtime import build_participant_export, compute_chat_status

router = APIRouter(tags=["sessions"])


def _effective_participant_names(session) -> list:
    """Human name pool used at join (letters after bots when Admin list is empty)."""
    from participant_naming import participant_name_pool

    min_h, _ = resolve_human_group_bounds(session)
    return participant_name_pool(session, min_h)


@router.get("/api/admin/human-defaults", dependencies=[Depends(require_auth)])
async def get_human_defaults():
    from human_defaults import HUMAN_LIKE_BOT, HUMAN_LIKE_PROMPT, HUMAN_LIKE_SESSION

    from env_defaults import env_defaults_dict

    return {
        "session": HUMAN_LIKE_SESSION,
        "bot": HUMAN_LIKE_BOT,
        "prompt": HUMAN_LIKE_PROMPT,
        "gpt_chat_models": list(GPT_CHAT_MODELS),
        "env_defaults": env_defaults_dict(),
    }


@router.get("/api/sessions", dependencies=[Depends(require_auth)])
async def list_sessions(request: Request):
    principal = require_auth(request)
    owner = None if is_super_admin(principal) else principal.get("account_id")
    return {"sessions": match_manager.get_all_sessions_summary(owner)}


@router.post("/api/sessions/create", dependencies=[Depends(require_auth)])
async def create_session(data: SessionCreateRequest, request: Request):
    try:
        principal = require_auth(request)
        owner_id = principal.get("account_id") if principal.get("type") == "account" else None
        cleaned_bots = []
        for bot in data.bots:
            name = (bot.get("name") or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="Each bot must have a non-empty name")
            cleaned_bots.append({
                **bot,
                "name": name,
                "model": normalize_gpt_chat_model(bot.get("model")),
            })

        session_id = match_manager.create_session(
            name=data.session_name,
            group_size=data.group_size,
            min_humans_per_group=data.min_humans_per_group,
            max_humans_per_group=data.max_humans_per_group,
            bot_enabled=data.bot_enabled,
            bots=cleaned_bots,
            survey_open_days=data.survey_open_days,
            group_chat_duration_minutes=data.group_chat_duration_minutes,
            participant_names=data.participant_names,
            session_mode=data.session_mode,
            qualtrics_handoff_enabled=data.qualtrics_handoff_enabled,
            qualtrics_store_chat=data.qualtrics_store_chat,
            qualtrics_field_transcript=data.qualtrics_field_transcript,
            qualtrics_field_status=data.qualtrics_field_status,
            ai_starts_conversation=data.ai_starts_conversation,
            turn_mode=data.turn_mode,
            turn_duration_seconds=data.turn_duration_seconds,
            assignment_mode=data.assignment_mode,
            condition_enabled=data.condition_enabled,
            style_mimic_enabled=data.style_mimic_enabled,
            style_mimic_target=data.style_mimic_target,
            bot_reply_on_any_message=data.bot_reply_on_any_message,
            max_chain_depth=data.max_chain_depth,
            use_mentions=data.use_mentions,
            mention_prob=data.mention_prob,
            self_correction_prob=data.self_correction_prob,
            group_spend_cap_usd=data.group_spend_cap_usd,
            owner_account_id=owner_id,
            parallel_start_jitter_sec=data.parallel_start_jitter_sec,
            rethink_seconds=data.rethink_seconds,
            max_refresh_attempts=data.max_refresh_attempts,
            qualtrics_log_mode=data.qualtrics_log_mode,
        )
        activity_logger.log_session_started(session_id, data.session_name)
        return {"status": "success", "session_id": session_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        error_id = error_handler.handle_exception(e, "create_session")
        return {"status": "error", "message": str(e), "error_id": error_id}


@router.get("/api/sessions/{session_id}/config")
async def get_session_config(
    session_id: str,
    participant_id: Optional[str] = Query(None),
    condition: Optional[str] = Query(None),
):
    from study_conditions import apply_disclosure_to_bots, assign_group_disclosure, resolve_ai_disclosed_bot

    session = match_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    bots = list(session.bots)
    ai_disclosed_bot = None
    study_condition = None
    condition_active = getattr(session, "condition_enabled", True)
    effective_condition = condition if condition_active else None

    if condition_active:
        if participant_id and participant_id in match_manager.user_locations:
            loc = match_manager.user_locations[participant_id]
            if loc.get("session_id") == session_id:
                gid = loc.get("group_id")
                group_info = match_manager.get_group_info(session_id, gid)
                if group_info:
                    if "ai_disclosed_bot" not in group_info and session.bots:
                        assign_group_disclosure(
                            session.bots,
                            group_info.get("condition") or effective_condition,
                            group_info,
                        )
                    ai_disclosed_bot = group_info.get("ai_disclosed_bot")
                    study_condition = group_info.get("study_condition")
                    bots = apply_disclosure_to_bots(session.bots, ai_disclosed_bot)
        elif effective_condition and session.bots:
            ai_disclosed_bot, study_condition = resolve_ai_disclosed_bot(session.bots, effective_condition)
            bots = apply_disclosure_to_bots(session.bots, ai_disclosed_bot)

    return {
        "session_id": session.session_id,
        "session_name": session.name,
        "bot_enabled": session.bot_enabled,
        "bots": bots,
        "ai_disclosed_bot": ai_disclosed_bot,
        "study_condition": study_condition,
        "group_size": session.group_size,
        "min_humans_per_group": getattr(session, "min_humans_per_group", session.group_size),
        "max_humans_per_group": getattr(session, "max_humans_per_group", session.group_size),
        "participant_names": session.participant_names,
        "effective_participant_names": _effective_participant_names(session),
        "session_mode": session.session_mode,
        "history_limit": session.history_limit,
        "qualtrics_handoff_enabled": session.qualtrics_handoff_enabled,
        "qualtrics_store_chat": session.qualtrics_store_chat,
        "qualtrics_enabled": bool(session.qualtrics_handoff_enabled and session.qualtrics_store_chat),
        "qualtrics_field_transcript": session.qualtrics_field_transcript,
        "qualtrics_field_status": session.qualtrics_field_status,
        "ai_starts_conversation": session.ai_starts_conversation,
        "turn_mode": session.turn_mode,
        "turn_duration_seconds": session.turn_duration_seconds,
        "assignment_mode": session.assignment_mode,
        "condition_enabled": getattr(session, "condition_enabled", True),
        "survey_open_days": session.survey_open_days,
        "group_chat_duration_minutes": session.group_chat_duration_minutes,
        "parallel_start_jitter_sec": getattr(session, "parallel_start_jitter_sec", 1.5),
        "rethink_seconds": getattr(session, "rethink_seconds", 2.0),
        "max_refresh_attempts": getattr(session, "max_refresh_attempts", 2),
        "qualtrics_log_mode": getattr(session, "qualtrics_log_mode", "transcript"),
    }


@router.get("/api/sessions/{session_id}/admin", dependencies=[Depends(require_auth)])
async def get_session_admin_detail(session_id: str, request: Request):
    session = match_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    require_session_access(request, getattr(session, "owner_account_id", None))
    data = match_manager.session_to_admin_dict(session)
    data["is_open"] = match_manager.is_session_open(session)
    try:
        created = session.created_at
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        data["survey_closes_at"] = (created + timedelta(days=session.survey_open_days)).isoformat()
    except (TypeError, ValueError):
        data["survey_closes_at"] = None
    return data


@router.put("/api/sessions/{session_id}", dependencies=[Depends(require_auth)])
async def modify_session(session_id: str, data: SessionUpdateRequest, request: Request):
    session = match_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    require_session_access(request, getattr(session, "owner_account_id", None))
    try:
        payload = data.model_dump(exclude_unset=True)
        if "bots" in payload and payload["bots"] is not None:
            cleaned = []
            for bot in payload["bots"]:
                name = (bot.get("name") or "").strip()
                if not name:
                    raise HTTPException(status_code=400, detail="Each bot must have a non-empty name")
                cleaned.append({
                    **bot,
                    "name": name,
                    "model": normalize_gpt_chat_model(bot.get("model")),
                })
            payload["bots"] = cleaned
        principal = require_auth(request)
        if (
            principal.get("type") == "account"
            and not getattr(session, "owner_account_id", None)
            and principal.get("account_id")
        ):
            session.owner_account_id = principal["account_id"]
        if not match_manager.update_session(session_id, payload):
            raise HTTPException(status_code=500, detail="Failed to save session configuration")
        return {"status": "success", "session_id": session_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        error_id = error_handler.handle_exception(e, "modify_session")
        return {"status": "error", "message": str(e), "error_id": error_id}


@router.get("/api/export/participant/{session_id}/{participant_id}")
async def export_participant_chat(session_id: str, participant_id: str):
    session = match_manager.get_session(session_id)
    data = await build_participant_export(session_id, participant_id)
    if not data.get("group_id"):
        raise HTTPException(status_code=404, detail="No chat found for this participant in this session")
    if session:
        group_info = match_manager.get_group_info(session_id, data["group_id"]) or {}
        data.update(compute_chat_status(session, group_info, participant_id, data, "export"))
    return data


@router.post("/api/embed/handoff")
async def embed_handoff(body: EmbedHandoffRequest):
    session = match_manager.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    export = await build_participant_export(body.session_id, body.participant_id)
    group_info = None
    if export.get("group_id"):
        group_info = match_manager.get_group_info(body.session_id, export["group_id"]) or {}

    status = compute_chat_status(session, group_info, body.participant_id, export, body.reason)

    qualtrics_text = export.get("qualtrics_export_text") or export.get("transcript_text", "")
    return {
        **export,
        **status,
        "transcript_text": qualtrics_text,
        "qualtrics_handoff_enabled": session.qualtrics_handoff_enabled,
        "qualtrics_store_chat": session.qualtrics_store_chat,
        "qualtrics_field_transcript": session.qualtrics_field_transcript,
        "qualtrics_field_status": session.qualtrics_field_status,
    }


@router.get("/api/sessions/{session_id}/activity", dependencies=[Depends(require_auth)])
async def get_session_activity(session_id: str, request: Request, limit: int = 100):
    session = match_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    require_session_access(request, getattr(session, "owner_account_id", None))
    activities = activity_logger.get_recent_activities(session_id, limit=limit)
    return {"session_id": session_id, "total_activities": len(activities), "activities": activities}
