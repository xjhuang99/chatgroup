"""
Researcher accounts: email registration, username/password, per-account API spend cap.
Stored in config/accounts.json (not committed).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from env_defaults import default_account_spend_cap_usd

_ACCOUNTS_FILE = os.path.join("config", "accounts.json")
_lock = threading.Lock()
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,32}$")


def _empty_store() -> Dict[str, Any]:
    return {"accounts": {}, "email_index": {}, "username_index": {}}


def _load() -> Dict[str, Any]:
    os.makedirs("config", exist_ok=True)
    if not os.path.exists(_ACCOUNTS_FILE):
        return _empty_store()
    try:
        with open(_ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("accounts", {})
        data.setdefault("email_index", {})
        data.setdefault("username_index", {})
        return data
    except Exception:
        return _empty_store()


def _save(data: Dict[str, Any]) -> None:
    os.makedirs("config", exist_ok=True)
    with open(_ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"pbkdf2_sha256${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, dk_hex = stored.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return secrets.compare_digest(dk, expected)
    except Exception:
        return False


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _suggest_username(email: str, username_index: Dict[str, str]) -> str:
    local = _normalize_email(email).split("@", 1)[0]
    base = re.sub(r"[^a-zA-Z0-9._-]", "", local)[:24] or "user"
    if len(base) < 3:
        base = f"user{base}"
    candidate = base
    n = 2
    while candidate.lower() in {k.lower() for k in username_index}:
        candidate = f"{base}{n}"
        n += 1
    return candidate


def _generate_password(length: int = 12) -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _public_account(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "account_id": rec["account_id"],
        "email": rec["email"],
        "username": rec["username"],
        "spend_cap_usd": rec.get("spend_cap_usd", default_account_spend_cap_usd()),
        "created_at": rec.get("created_at"),
    }


def get_account(account_id: str) -> Optional[Dict[str, Any]]:
    data = _load()
    rec = data["accounts"].get(account_id)
    return dict(rec) if rec else None


def get_account_by_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    data = _load()
    for rec in data["accounts"].values():
        if secrets.compare_digest(rec.get("auth_token", ""), token):
            return dict(rec)
    return None


def get_account_by_username(username: str) -> Optional[Dict[str, Any]]:
    data = _load()
    aid = data["username_index"].get((username or "").strip())
    if not aid:
        return None
    rec = data["accounts"].get(aid)
    return dict(rec) if rec else None


def verify_account_login(username: str, password: str) -> Optional[Dict[str, Any]]:
    rec = get_account_by_username(username.strip())
    if not rec or not verify_password(password, rec.get("password_hash", "")):
        return None
    return rec


def register_account(
    email: str,
    *,
    username: Optional[str] = None,
    password: Optional[str] = None,
    spend_cap_usd: Optional[float] = None,
) -> Tuple[Dict[str, Any], str]:
    """
    Create account. Returns (public fields + one-time plaintext password, message).
    """
    em = _normalize_email(email)
    if not _EMAIL_RE.match(em):
        raise ValueError("Invalid email address")

    generated_password = (password or "").strip() or _generate_password()
    if len(generated_password) < 8:
        raise ValueError("Password must be at least 8 characters")

    with _lock:
        data = _load()
        if em in data["email_index"]:
            raise ValueError("Email already registered")

        uname = (username or "").strip() or _suggest_username(em, data["username_index"])
        if not _USERNAME_RE.match(uname):
            raise ValueError("Username must be 3–32 characters (letters, numbers, . _ -)")
        if uname.lower() in {k.lower() for k in data["username_index"]}:
            raise ValueError("Username already taken")

        account_id = f"ACC-{uuid.uuid4().hex[:5].upper()}"
        cap = spend_cap_usd if spend_cap_usd is not None else default_account_spend_cap_usd()
        auth_token = secrets.token_urlsafe(32)
        rec = {
            "account_id": account_id,
            "email": em,
            "username": uname,
            "password_hash": _hash_password(generated_password),
            "spend_cap_usd": max(1.0, float(cap)),
            "auth_token": auth_token,
            "created_at": datetime.now().isoformat(),
        }
        data["accounts"][account_id] = rec
        data["email_index"][em] = account_id
        data["username_index"][uname] = account_id
        _save(data)

    out = _public_account(rec)
    out["password"] = generated_password
    return out, "Account created"


def rotate_auth_token(account_id: str) -> str:
    with _lock:
        data = _load()
        rec = data["accounts"].get(account_id)
        if not rec:
            raise ValueError("Account not found")
        token = secrets.token_urlsafe(32)
        rec["auth_token"] = token
        _save(data)
    return token


def update_account_profile(
    account_id: str,
    *,
    current_password: str,
    username: Optional[str] = None,
    new_password: Optional[str] = None,
) -> Dict[str, Any]:
    with _lock:
        data = _load()
        rec = data["accounts"].get(account_id)
        if not rec:
            raise ValueError("Account not found")
        if not verify_password(current_password, rec.get("password_hash", "")):
            raise ValueError("Current password is incorrect")

        if username is not None:
            uname = username.strip()
            if not _USERNAME_RE.match(uname):
                raise ValueError("Username must be 3–32 characters (letters, numbers, . _ -)")
            old_uname = rec["username"]
            if uname.lower() != old_uname.lower():
                if uname.lower() in {k.lower() for k in data["username_index"]}:
                    raise ValueError("Username already taken")
                del data["username_index"][old_uname]
                data["username_index"][uname] = account_id
                rec["username"] = uname

        if new_password is not None:
            pwd = new_password.strip()
            if len(pwd) < 8:
                raise ValueError("New password must be at least 8 characters")
            rec["password_hash"] = _hash_password(pwd)
            rec["auth_token"] = secrets.token_urlsafe(32)

        _save(data)
        return _public_account(rec)


def list_accounts_public() -> List[Dict[str, Any]]:
    data = _load()
    return [_public_account(rec) for rec in data["accounts"].values()]


def admin_set_spend_cap(account_id: str, spend_cap_usd: float) -> Dict[str, Any]:
    """Super-admin: adjust per-researcher API budget (USD)."""
    with _lock:
        data = _load()
        rec = data["accounts"].get(account_id)
        if not rec:
            raise ValueError("Account not found")
        rec["spend_cap_usd"] = max(1.0, float(spend_cap_usd))
        _save(data)
        return _public_account(rec)


def account_owns_session(account_id: str, session_owner: Optional[str]) -> bool:
    if not session_owner:
        return False
    return session_owner == account_id
