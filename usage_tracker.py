"""
OpenAI usage tracking, per-group spend caps, and cost rollups for the dashboard.
Prices are USD per 1M tokens (slightly above public OpenAI list for buffer).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from env_defaults import (
    default_account_spend_cap_usd,
    default_group_spend_cap_usd,
    default_session_spend_cap_usd,
    env_defaults_dict,
)

_LEDGER_DIR = "config"
_LEDGER_FILE = os.path.join(_LEDGER_DIR, "usage_ledger.jsonl")
_ROLLUP_FILE = os.path.join(_LEDGER_DIR, "usage_rollups.json")
_lock = threading.Lock()

# USD per 1M tokens (input / output) — ~10% above typical OpenAI list
MODEL_PRICING_PER_1M: Dict[str, Dict[str, float]] = {
    "gpt-4o": {"input": 2.75, "output": 11.0},
    "gpt-5": {"input": 5.50, "output": 22.0},
    "gpt-5.5": {"input": 6.60, "output": 26.0},
    "gpt-5-mini": {"input": 0.55, "output": 2.20},
    "deepseek-chat": {"input": 0.30, "output": 1.20},
    "deepseek-reasoner": {"input": 0.60, "output": 2.40},
    "default": {"input": 3.30, "output": 13.20},
}


class SpendCapExceeded(Exception):
    """Raised when a group has hit its API spend cap."""


def _pricing_for_model(model: str) -> Dict[str, float]:
    m = (model or "").strip().lower()
    if m in MODEL_PRICING_PER_1M:
        return MODEL_PRICING_PER_1M[m]
    for key in MODEL_PRICING_PER_1M:
        if key != "default" and m.startswith(key):
            return MODEL_PRICING_PER_1M[key]
    return MODEL_PRICING_PER_1M["default"]


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = _pricing_for_model(model)
    return (prompt_tokens * rates["input"] + completion_tokens * rates["output"]) / 1_000_000


def estimate_tokens_from_text(text: str) -> int:
    return max(1, len(text or "") // 4)


def _empty_rollups() -> Dict[str, Any]:
    return {
        "groups": {},
        "sessions": {},
        "accounts": {},
        "global": {
            "spend_usd": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "api_calls": 0,
        },
        "hourly": {},
        "updated_at": None,
    }


def _load_rollups() -> Dict[str, Any]:
    os.makedirs(_LEDGER_DIR, exist_ok=True)
    if not os.path.exists(_ROLLUP_FILE):
        return _empty_rollups()
    try:
        with open(_ROLLUP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key in ("groups", "sessions", "accounts", "global", "hourly"):
            data.setdefault(key, _empty_rollups()[key])
        return data
    except Exception:
        return _empty_rollups()


def _save_rollups(data: Dict[str, Any]) -> None:
    os.makedirs(_LEDGER_DIR, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    with open(_ROLLUP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _bump(bucket: Dict[str, Any], prompt_tokens: int, completion_tokens: int, cost: float) -> None:
    bucket["prompt_tokens"] = int(bucket.get("prompt_tokens", 0)) + prompt_tokens
    bucket["completion_tokens"] = int(bucket.get("completion_tokens", 0)) + completion_tokens
    bucket["api_calls"] = int(bucket.get("api_calls", 0)) + 1
    bucket["spend_usd"] = round(float(bucket.get("spend_usd", 0)) + cost, 6)


def _resolve_owner_account_id(session_id: str) -> Optional[str]:
    from match_manager import match_manager

    session = match_manager.get_session(session_id)
    if not session:
        return None
    owner = getattr(session, "owner_account_id", None)
    return str(owner).strip() if owner else None


def get_account_usage(account_id: str) -> Dict[str, Any]:
    rollups = _load_rollups()
    return dict(rollups.get("accounts", {}).get(account_id, {}))


def get_account_spend_usd(account_id: str) -> float:
    return float(get_account_usage(account_id).get("spend_usd", 0))


def record_usage(
    *,
    session_id: str,
    group_id: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    call_type: str = "chat",
) -> Dict[str, Any]:
    """Persist one API call and update rollups. Returns cost breakdown."""
    cost = estimate_cost_usd(model, prompt_tokens, completion_tokens)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "group_id": group_id,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": round(cost, 6),
        "call_type": call_type,
    }
    with _lock:
        os.makedirs(_LEDGER_DIR, exist_ok=True)
        with open(_LEDGER_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        rollups = _load_rollups()
        gid = group_id or "_unknown"
        sid = session_id or "_unknown"
        if gid not in rollups["groups"]:
            rollups["groups"][gid] = {
                "session_id": sid,
                "spend_usd": 0.0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "api_calls": 0,
            }
        if sid not in rollups["sessions"]:
            rollups["sessions"][sid] = {
                "spend_usd": 0.0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "api_calls": 0,
            }
        _bump(rollups["groups"][gid], prompt_tokens, completion_tokens, cost)
        _bump(rollups["sessions"][sid], prompt_tokens, completion_tokens, cost)
        _bump(rollups["global"], prompt_tokens, completion_tokens, cost)

        owner_id = _resolve_owner_account_id(sid)
        if owner_id:
            if owner_id not in rollups.setdefault("accounts", {}):
                rollups["accounts"][owner_id] = {
                    "spend_usd": 0.0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "api_calls": 0,
                }
            _bump(rollups["accounts"][owner_id], prompt_tokens, completion_tokens, cost)

        hour_key = datetime.now().strftime("%Y-%m-%dT%H")
        if hour_key not in rollups["hourly"]:
            rollups["hourly"][hour_key] = {"spend_usd": 0.0, "api_calls": 0}
        rollups["hourly"][hour_key]["spend_usd"] = round(
            float(rollups["hourly"][hour_key].get("spend_usd", 0)) + cost, 6
        )
        rollups["hourly"][hour_key]["api_calls"] = int(
            rollups["hourly"][hour_key].get("api_calls", 0)
        ) + 1
        _save_rollups(rollups)

    try:
        from usage_alerts import maybe_send_cap_threshold_alerts, maybe_send_usage_alerts

        maybe_send_cap_threshold_alerts(
            rollups, session_id=session_id, group_id=group_id, cost_usd=cost
        )
        maybe_send_usage_alerts(rollups, group_id=group_id, session_id=session_id, cost_usd=cost)
    except Exception as e:
        print(f"⚠️ usage alert check failed: {e}")

    return entry


def get_group_usage(group_id: str) -> Dict[str, Any]:
    rollups = _load_rollups()
    return dict(rollups.get("groups", {}).get(group_id, {}))


def get_session_usage(session_id: str) -> Dict[str, Any]:
    rollups = _load_rollups()
    return dict(rollups.get("sessions", {}).get(session_id, {}))


def get_global_usage() -> Dict[str, Any]:
    rollups = _load_rollups()
    return {
        "global": rollups.get("global", {}),
        "hourly": rollups.get("hourly", {}),
        "updated_at": rollups.get("updated_at"),
        "default_group_cap_usd": default_group_spend_cap_usd(),
        "pricing_note": "USD per 1M tokens; rates include ~10% buffer over list.",
        "models": MODEL_PRICING_PER_1M,
    }


def get_dashboard_summary() -> Dict[str, Any]:
    rollups = _load_rollups()
    groups = rollups.get("groups", {})
    sessions = rollups.get("sessions", {})
    top_groups = sorted(
        [{"group_id": k, **v} for k, v in groups.items()],
        key=lambda x: x.get("spend_usd", 0),
        reverse=True,
    )[:20]
    top_sessions = sorted(
        [{"session_id": k, **v} for k, v in sessions.items()],
        key=lambda x: x.get("spend_usd", 0),
        reverse=True,
    )[:20]
    hour_key = datetime.now().strftime("%Y-%m-%dT%H")
    hour_spend = float(rollups.get("hourly", {}).get(hour_key, {}).get("spend_usd", 0))
    return {
        "global": rollups.get("global", {}),
        "hour_spend_usd": hour_spend,
        "top_groups": top_groups,
        "top_sessions": top_sessions,
        "default_group_cap_usd": default_group_spend_cap_usd(),
        "default_account_cap_usd": default_account_spend_cap_usd(),
        "env_defaults": env_defaults_dict(),
        "updated_at": rollups.get("updated_at"),
    }


def resolve_group_spend_cap(
    session_id: str,
    group_id: str,
    group_info: Optional[dict] = None,
) -> float:
    if group_info and group_info.get("spend_cap_usd") is not None:
        return max(0.0, float(group_info["spend_cap_usd"]))
    from match_manager import match_manager

    session = match_manager.get_session(session_id)
    if session and getattr(session, "group_spend_cap_usd", None) is not None:
        return max(0.0, float(session.group_spend_cap_usd))
    return default_group_spend_cap_usd()


def get_group_spend_usd(group_id: str) -> float:
    return float(get_group_usage(group_id).get("spend_usd", 0))


def get_session_spend_usd(session_id: str) -> float:
    return float(get_session_usage(session_id).get("spend_usd", 0))


def check_can_spend(
    session_id: str,
    group_id: str,
    group_info: Optional[dict] = None,
) -> Tuple[bool, str]:
    """Return (allowed, reason)."""
    if not group_id:
        return True, ""
    from group_idle import is_group_chat_live
    from match_manager import match_manager

    if not is_group_chat_live(match_manager, session_id, group_id):
        return False, "Chat group has ended"

    session = match_manager.get_session(session_id)
    owner_id = getattr(session, "owner_account_id", None) if session else None
    if owner_id:
        from account_store import get_account

        acct = get_account(str(owner_id))
        if acct:
            acap = float(acct.get("spend_cap_usd", default_account_spend_cap_usd()))
            aspent = get_account_spend_usd(str(owner_id))
            if aspent >= acap:
                return False, f"Account API spend cap reached (${acap:.2f})"

    cap = resolve_group_spend_cap(session_id, group_id, group_info)
    spent = get_group_spend_usd(group_id)
    if spent >= cap:
        return False, f"Group API spend cap reached (${cap:.2f})"
    session_cap = default_session_spend_cap_usd()
    if session_cap is not None and get_session_spend_usd(session_id) >= session_cap:
        return False, f"Session API spend cap reached (${session_cap:.2f})"
    return True, ""


def usage_from_completion(response, prompt_messages: Optional[list] = None) -> Tuple[int, int]:
    """Extract token counts from OpenAI response or estimate."""
    usage = getattr(response, "usage", None)
    if usage:
        return int(getattr(usage, "prompt_tokens", 0) or 0), int(
            getattr(usage, "completion_tokens", 0) or 0
        )
    prompt_est = 0
    if prompt_messages:
        for m in prompt_messages:
            prompt_est += estimate_tokens_from_text(str(m.get("content", "")))
    completion_est = estimate_tokens_from_text(
        response.choices[0].message.content if response.choices else ""
    )
    return prompt_est, completion_est
