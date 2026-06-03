from fastapi import APIRouter, Depends, HTTPException, Request

from account_store import get_account
from admin_auth import is_super_admin, require_auth, require_session_access
from match_manager import match_manager
from env_defaults import default_account_spend_cap_usd
from usage_tracker import (
    MODEL_PRICING_PER_1M,
    default_group_spend_cap_usd,
    get_account_spend_usd,
    get_dashboard_summary,
    get_global_usage,
    get_group_usage,
    get_session_usage,
)

router = APIRouter(tags=["usage"])


@router.get("/api/admin/usage", dependencies=[Depends(require_auth)])
async def admin_usage_summary(request: Request):
    principal = require_auth(request)
    summary = get_dashboard_summary()
    summary["pricing_per_1m_usd"] = MODEL_PRICING_PER_1M
    if principal.get("type") == "account":
        aid = principal["account_id"]
        acct = get_account(aid) or {}
        cap = float(acct.get("spend_cap_usd") or default_account_spend_cap_usd())
        spent = get_account_spend_usd(aid)
        summary["account"] = {
            "account_id": aid,
            "email": principal.get("email"),
            "username": principal.get("username"),
            "spend_cap_usd": cap,
            "spend_usd": round(spent, 4),
            "spend_remaining_usd": round(max(0.0, cap - spent), 4),
        }
        owned = {
            sid
            for sid, cfg in match_manager.sessions.items()
            if getattr(cfg, "owner_account_id", None) == aid
        }
        summary["top_sessions"] = [s for s in summary.get("top_sessions", []) if s.get("session_id") in owned]
        summary["top_groups"] = [g for g in summary.get("top_groups", []) if g.get("session_id") in owned]
    return summary


@router.get("/api/admin/usage/sessions/{session_id}", dependencies=[Depends(require_auth)])
async def admin_session_usage(session_id: str, request: Request):
    session = match_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    require_session_access(request, getattr(session, "owner_account_id", None))
    return {
        "session_id": session_id,
        "usage": get_session_usage(session_id),
        "default_group_cap_usd": default_group_spend_cap_usd(),
    }


@router.get("/api/admin/usage/groups/{group_id}", dependencies=[Depends(require_auth)])
async def admin_group_usage(group_id: str, request: Request):
    session_id = match_manager.resolve_session_id_for_group(group_id)
    if not session_id:
        raise HTTPException(status_code=404, detail="Room not found")
    session = match_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    require_session_access(request, getattr(session, "owner_account_id", None))
    usage = get_group_usage(group_id)
    return {"group_id": group_id, "session_id": session_id, "usage": usage}


@router.get("/api/admin/usage/global", dependencies=[Depends(require_auth)])
async def admin_global_usage(request: Request):
    principal = require_auth(request)
    if not is_super_admin(principal):
        return {"restricted": True, "message": "Global usage is super-admin only"}
    return get_global_usage()
