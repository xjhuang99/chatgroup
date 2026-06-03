"""
Authentication: env super-admin + per-email researcher accounts (cookie token).
"""

from __future__ import annotations

import hashlib
import os
import secrets
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, Response

from account_store import get_account_by_token, verify_account_login

COOKIE_NAME = "actr_auth"
_COOKIE_MAX_AGE = 86400 * 7
_ADMIN_PREFIX = "admin:"
_ACCOUNT_PREFIX = "acct:"


def _credentials() -> tuple[str, str]:
    return (
        os.getenv("ADMIN_USERNAME", "ACTR2026").strip(),
        os.getenv("ADMIN_PASSWORD", "ACTR2026"),
    )


def admin_session_token() -> str:
    explicit = (os.getenv("ADMIN_AUTH_SECRET") or "").strip()
    if explicit:
        return explicit
    user, pwd = _credentials()
    return hashlib.sha256(f"{user}:{pwd}".encode()).hexdigest()


def verify_admin_credentials(username: str, password: str) -> bool:
    expected_user, expected_pwd = _credentials()
    return secrets.compare_digest(username.strip(), expected_user) and secrets.compare_digest(
        password, expected_pwd
    )


def _encode_admin_cookie() -> str:
    return f"{_ADMIN_PREFIX}{admin_session_token()}"


def _encode_account_cookie(auth_token: str) -> str:
    return f"{_ACCOUNT_PREFIX}{auth_token}"


def get_auth_principal(request: Request) -> Optional[Dict[str, Any]]:
    """Return {type: admin|account, ...} or None."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    if token.startswith(_ADMIN_PREFIX):
        expected = _encode_admin_cookie()
        if secrets.compare_digest(token, expected):
            return {"type": "admin", "username": _credentials()[0]}
        return None
    if token.startswith(_ACCOUNT_PREFIX):
        auth_token = token[len(_ACCOUNT_PREFIX) :]
        rec = get_account_by_token(auth_token)
        if rec:
            from account_store import get_account

            fresh = get_account(rec["account_id"]) or rec
            return {
                "type": "account",
                "account_id": fresh["account_id"],
                "email": fresh["email"],
                "username": fresh["username"],
                "spend_cap_usd": fresh.get("spend_cap_usd"),
            }
    return None


def is_super_admin(principal: Optional[Dict[str, Any]]) -> bool:
    return bool(principal and principal.get("type") == "admin")


def check_auth(request: Request) -> bool:
    return get_auth_principal(request) is not None


def require_admin(request: Request) -> None:
    principal = get_auth_principal(request)
    if not is_super_admin(principal):
        raise HTTPException(status_code=401, detail="Admin authentication required")


def require_auth(request: Request) -> Dict[str, Any]:
    principal = get_auth_principal(request)
    if not principal:
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal


def require_session_access(request: Request, owner_account_id: Optional[str]) -> Dict[str, Any]:
    """Super-admin: any session. Account: own sessions, or legacy sessions with no owner."""
    principal = require_auth(request)
    if is_super_admin(principal):
        return principal
    if principal.get("type") == "account":
        if not owner_account_id or owner_account_id == principal.get("account_id"):
            return principal
    raise HTTPException(status_code=403, detail="Not allowed for this session")


def set_admin_cookie(response: Response) -> None:
    _set_cookie(response, _encode_admin_cookie())


def set_account_cookie(response: Response, auth_token: str) -> None:
    _set_cookie(response, _encode_account_cookie(auth_token))


def _set_cookie(response: Response, value: str) -> None:
    secure = os.getenv("ADMIN_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
    response.set_cookie(
        key=COOKIE_NAME,
        value=value,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
        secure=secure,
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


# Back-compat aliases
set_auth_cookie = set_admin_cookie


def login_with_credentials(username: str, password: str) -> Optional[tuple[str, Dict[str, Any]]]:
    """Returns (cookie_value, principal) or None."""
    if verify_admin_credentials(username, password):
        return _encode_admin_cookie(), {"type": "admin", "username": username.strip()}
    rec = verify_account_login(username, password)
    if rec:
        return _encode_account_cookie(rec["auth_token"]), {
            "type": "account",
            "account_id": rec["account_id"],
            "email": rec["email"],
            "username": rec["username"],
            "spend_cap_usd": rec.get("spend_cap_usd"),
        }
    return None
