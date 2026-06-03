import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from account_store import get_account, register_account, update_account_profile
from actr.schemas import (
    AccountProfileUpdateRequest,
    AccountRegisterRequest,
    AdminAccountCapUpdate,
    AdminLoginRequest,
)
from admin_auth import (
    clear_auth_cookie,
    get_auth_principal,
    is_super_admin,
    login_with_credentials,
    require_admin,
    require_auth,
    set_account_cookie,
    set_admin_cookie,
)
from env_defaults import default_account_spend_cap_usd
from usage_tracker import get_account_spend_usd

router = APIRouter(tags=["auth"])


def _public_register_allowed() -> bool:
    return os.getenv("ALLOW_ACCOUNT_REGISTER", "true").lower() in ("1", "true", "yes")


@router.post("/api/auth/login")
async def admin_login(body: AdminLoginRequest):
    result = login_with_credentials(body.username, body.password)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    cookie_value, principal = result
    response = JSONResponse({"status": "success", "principal": principal})
    if principal.get("type") == "admin":
        set_admin_cookie(response)
    else:
        rec = get_account(principal["account_id"])
        if rec:
            set_account_cookie(response, rec["auth_token"])
    return response


@router.post("/api/auth/register")
async def account_register(body: AccountRegisterRequest):
    if not _public_register_allowed():
        raise HTTPException(status_code=403, detail="Registration is disabled")
    try:
        out, _msg = register_account(
            body.email,
            username=body.username,
            password=body.password,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    rec = get_account(out["account_id"])
    response = JSONResponse(
        {
            "status": "success",
            "account": {
                "account_id": out["account_id"],
                "email": out["email"],
                "username": out["username"],
                "spend_cap_usd": out["spend_cap_usd"],
            },
            "credentials": {
                "username": out["username"],
                "password": out["password"],
            },
            "message": "Save these credentials now; the password is shown only once.",
        }
    )
    if rec:
        set_account_cookie(response, rec["auth_token"])
    return response


@router.put("/api/auth/profile")
async def account_profile(body: AccountProfileUpdateRequest, request: Request):
    principal = require_auth(request)
    if principal.get("type") != "account":
        raise HTTPException(status_code=403, detail="Only researcher accounts can update profile")
    try:
        updated = update_account_profile(
            principal["account_id"],
            current_password=body.current_password,
            username=body.username,
            new_password=body.new_password,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    rec = get_account(principal["account_id"])
    response = JSONResponse({"status": "success", "account": updated})
    if rec and body.new_password:
        set_account_cookie(response, rec["auth_token"])
    return response


@router.post("/api/auth/logout")
async def admin_logout():
    response = JSONResponse({"status": "success"})
    clear_auth_cookie(response)
    return response


@router.get("/api/auth/me")
async def admin_auth_me(request: Request):
    principal = get_auth_principal(request)
    if not principal:
        return {"authenticated": False}
    payload = {"authenticated": True, **principal}
    if principal.get("type") == "account":
        from account_store import get_account

        aid = principal["account_id"]
        fresh = get_account(aid) or {}
        cap = float(
            fresh.get("spend_cap_usd")
            or principal.get("spend_cap_usd")
            or default_account_spend_cap_usd()
        )
        payload["spend_cap_usd"] = cap
        spent = get_account_spend_usd(aid)
        payload["spend_usd"] = round(spent, 4)
        payload["spend_remaining_usd"] = round(max(0.0, cap - spent), 4)
    return payload


@router.get("/api/admin/accounts", dependencies=[Depends(require_admin)])
async def list_researcher_accounts():
    from account_store import list_accounts_public
    from match_manager import match_manager

    accounts = list_accounts_public()
    for a in accounts:
        aid = a["account_id"]
        cap = float(a.get("spend_cap_usd") or default_account_spend_cap_usd())
        spent = get_account_spend_usd(aid)
        a["spend_usd"] = round(spent, 4)
        a["spend_remaining_usd"] = round(max(0.0, cap - spent), 4)
        a["session_count"] = sum(
            1
            for cfg in match_manager.sessions.values()
            if getattr(cfg, "owner_account_id", None) == aid
        )
    return {"accounts": accounts, "default_cap_usd": default_account_spend_cap_usd()}


@router.put("/api/admin/accounts/{account_id}", dependencies=[Depends(require_admin)])
async def admin_update_account_cap(account_id: str, body: AdminAccountCapUpdate):
    from account_store import admin_set_spend_cap

    try:
        updated = admin_set_spend_cap(account_id, body.spend_cap_usd)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    cap = float(updated.get("spend_cap_usd") or default_account_spend_cap_usd())
    spent = get_account_spend_usd(account_id)
    return {
        "status": "success",
        "account": {
            **updated,
            "spend_usd": round(spent, 4),
            "spend_remaining_usd": round(max(0.0, cap - spent), 4),
        },
    }
