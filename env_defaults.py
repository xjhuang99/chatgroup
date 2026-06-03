"""
Canonical defaults for .env-driven settings.

Keep in sync with .env.example and README.md Environment table.
Import accessors from here instead of duplicating os.getenv(..., "…") strings.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

# Documented values (for docs/UI when env is unset)
DEFAULT_GROUP_SPEND_CAP_USD = 8.0
DEFAULT_ACCOUNT_SPEND_CAP_USD = 200.0
DEFAULT_ALERT_HOURLY_SPEND_USD = 40.0
DEFAULT_ALERT_GROUP_BURST_USD = 15.0
DEFAULT_ALERT_COOLDOWN_MINUTES = 30
DEFAULT_ALERT_CAP_WARN_RATIO = 0.8


def _float_env(name: str, fallback: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return fallback
    try:
        return float(raw)
    except ValueError:
        return fallback


def _int_env(name: str, fallback: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return fallback
    try:
        return int(raw)
    except ValueError:
        return fallback


def default_group_spend_cap_usd() -> float:
    return max(0.5, _float_env("GROUP_SPEND_CAP_USD", DEFAULT_GROUP_SPEND_CAP_USD))


def default_account_spend_cap_usd() -> float:
    return max(1.0, _float_env("ACCOUNT_SPEND_CAP_USD", DEFAULT_ACCOUNT_SPEND_CAP_USD))


def default_session_spend_cap_usd() -> Optional[float]:
    raw = (os.getenv("SESSION_SPEND_CAP_USD") or "").strip()
    if not raw:
        return None
    try:
        return max(1.0, float(raw))
    except ValueError:
        return None


def default_alert_hourly_spend_usd() -> float:
    return _float_env("ALERT_HOURLY_SPEND_USD", DEFAULT_ALERT_HOURLY_SPEND_USD)


def default_alert_group_burst_usd() -> float:
    return _float_env("ALERT_GROUP_BURST_USD", DEFAULT_ALERT_GROUP_BURST_USD)


def default_alert_cooldown_minutes() -> int:
    return max(1, _int_env("ALERT_COOLDOWN_MINUTES", DEFAULT_ALERT_COOLDOWN_MINUTES))


def default_alert_cap_warn_ratio() -> float:
    return max(0.0, min(1.0, _float_env("ALERT_CAP_WARN_RATIO", DEFAULT_ALERT_CAP_WARN_RATIO)))


def env_defaults_dict() -> Dict[str, Any]:
    """Snapshot for APIs and admin UI (resolved from current process env)."""
    return {
        "group_spend_cap_usd": default_group_spend_cap_usd(),
        "account_spend_cap_usd": default_account_spend_cap_usd(),
        "session_spend_cap_usd": default_session_spend_cap_usd(),
        "alert_hourly_spend_usd": default_alert_hourly_spend_usd(),
        "alert_group_burst_usd": default_alert_group_burst_usd(),
        "alert_cooldown_minutes": default_alert_cooldown_minutes(),
        "alert_cap_warn_ratio": default_alert_cap_warn_ratio(),
    }
