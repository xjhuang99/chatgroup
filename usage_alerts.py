"""
Email alerts: cap thresholds (80% / 100%) and optional burst/hourly spikes.

All notification text is fixed English. Researchers receive cap alerts for budgets
they own; ALERT_EMAIL_TO receives every cap alert plus burst/hourly ops alerts.
"""

from __future__ import annotations

import json
import os
import smtplib
import threading
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional, Tuple

from env_defaults import (
    default_account_spend_cap_usd,
    default_alert_cap_warn_ratio,
    default_alert_cooldown_minutes,
    default_alert_group_burst_usd,
    default_alert_hourly_spend_usd,
)

_STATE_FILE = os.path.join("config", "usage_alert_state.json")
_last_burst_alert_at: Optional[datetime] = None
_burst_lock = threading.Lock()
_state_lock = threading.Lock()

# --- Fixed email copy (English) ---

FOOTER = (
    "This is an automated message from ACTR. "
    "Open Dashboard → Usage & cost for details."
)

CAP_LEVEL1_RESEARCHER_SUBJECT = "[ACTR] API budget warning (80%)"
CAP_LEVEL2_RESEARCHER_SUBJECT = "[ACTR] API budget limit reached"
CAP_LEVEL1_OPS_SUBJECT = "[ACTR] Ops: API budget warning (80%)"
CAP_LEVEL2_OPS_SUBJECT = "[ACTR] Ops: API budget limit reached"
BURST_OPS_SUBJECT = "[ACTR] Ops: API usage spike"


def _cap_body_researcher(
    *,
    level: int,
    budget_type: str,
    budget_id: str,
    spent: float,
    cap: float,
    pct: float,
    session_id: str,
    group_id: str,
) -> str:
    if level == 1:
        headline = (
            "Your ACTR API budget has reached 80% of its limit. "
            "Bot replies may continue for a short time."
        )
    else:
        headline = (
            "Your ACTR API budget limit has been reached. "
            "New bot API calls are blocked until you raise the cap or usage is reset."
        )
    lines = [
        headline,
        "",
        f"Budget type: {budget_type}",
        f"Reference: {budget_id}",
        f"Estimated spend: ${spent:.2f} USD",
        f"Budget cap: ${cap:.2f} USD",
        f"Usage: {pct:.1f}% of cap",
    ]
    if session_id:
        lines.append(f"Session: {session_id}")
    if group_id:
        lines.append(f"Chat group: {group_id}")
    lines.extend(["", FOOTER])
    return "\n".join(lines)


def _cap_body_ops(
    *,
    level: int,
    budget_type: str,
    budget_id: str,
    spent: float,
    cap: float,
    pct: float,
    session_id: str,
    group_id: str,
    owner_email: Optional[str],
) -> str:
    if level == 1:
        headline = "An ACTR API budget has crossed the 80% warning threshold."
    else:
        headline = "An ACTR API budget has reached its limit (100%). Bot API calls are blocked for that scope."
    lines = [
        headline,
        "",
        f"Budget type: {budget_type}",
        f"Reference: {budget_id}",
        f"Estimated spend: ${spent:.2f} USD",
        f"Budget cap: ${cap:.2f} USD",
        f"Usage: {pct:.1f}% of cap",
    ]
    if owner_email:
        lines.append(f"Session owner (registered): {owner_email}")
    if session_id:
        lines.append(f"Session: {session_id}")
    if group_id:
        lines.append(f"Chat group: {group_id}")
    lines.extend(["", FOOTER])
    return "\n".join(lines)


def _burst_body_ops(
    *,
    session_id: str,
    group_id: str,
    last_call_cost: float,
    reasons: List[str],
    at: datetime,
) -> str:
    lines = [
        "ACTR API usage has exceeded a configured spike threshold.",
        "",
        f"Time (UTC): {at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Session: {session_id or 'n/a'}",
        f"Chat group: {group_id or 'n/a'}",
        f"Last API call (estimated): ${last_call_cost:.4f} USD",
        "",
        "Triggers:",
    ]
    lines.extend(f"- {r}" for r in reasons)
    lines.extend(["", FOOTER])
    return "\n".join(lines)


def _parse_recipients(raw: str) -> List[str]:
    if not raw:
        return []
    parts = raw.replace(";", ",").split(",")
    return [p.strip() for p in parts if p.strip() and "@" in p]


def _ops_recipients() -> List[str]:
    return _parse_recipients(os.getenv("ALERT_EMAIL_TO") or "")


def _smtp_configured() -> bool:
    return bool((os.getenv("SMTP_HOST") or "").strip())


def _alert_enabled() -> bool:
    return _smtp_configured() and bool(_ops_recipients())


def _cap_alerts_enabled() -> bool:
    return _smtp_configured()


def _send_email(subject: str, body: str, to_addrs: List[str]) -> bool:
    host = (os.getenv("SMTP_HOST") or "").strip()
    uniq = list(dict.fromkeys(a for a in to_addrs if a))
    if not host or not uniq:
        return False
    port = int(os.getenv("SMTP_PORT", "587"))
    user = (os.getenv("SMTP_USER") or "").strip()
    password = (os.getenv("SMTP_PASSWORD") or "").replace(" ", "")
    from_addr = (os.getenv("SMTP_FROM") or user or "actr@localhost").strip()
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(uniq)

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            if use_tls:
                server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, uniq, msg.as_string())
        print(f"📧 Alert sent to {len(uniq)} recipient(s): {subject}")
        return True
    except Exception as e:
        print(f"⚠️ Failed to send alert email: {e}")
        return False


def _load_alert_state() -> Dict[str, Dict[str, bool]]:
    os.makedirs("config", exist_ok=True)
    if not os.path.exists(_STATE_FILE):
        return {}
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_alert_state(state: Dict[str, Dict[str, bool]]) -> None:
    os.makedirs("config", exist_ok=True)
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _account_email(account_id: str) -> Optional[str]:
    from account_store import get_account

    rec = get_account(account_id)
    if not rec:
        return None
    email = (rec.get("email") or "").strip().lower()
    return email if email and "@" in email else None


def _recipients_for_scope(owner_account_id: Optional[str]) -> Tuple[List[str], List[str]]:
    ops = _ops_recipients()
    researcher: List[str] = []
    if owner_account_id:
        em = _account_email(owner_account_id)
        if em:
            researcher = [em]
    return researcher, ops


def _scope_labels(scope_key: str) -> Tuple[str, str, str]:
    """Return (budget_type, budget_id, short_ref for subject)."""
    if scope_key.startswith("group:"):
        gid = scope_key.split(":", 1)[1]
        return "Per chat group", gid, f"group {gid}"
    if scope_key.startswith("session:"):
        sid = scope_key.split(":", 1)[1]
        return "Per session (all groups)", sid, f"session {sid}"
    if scope_key.startswith("account:"):
        aid = scope_key.split(":", 1)[1]
        em = _account_email(aid) or aid
        return "Researcher account (total)", em, f"account {em}"
    return "Budget", scope_key, scope_key


def _evaluate_cap_scope(
    state: Dict[str, Dict[str, bool]],
    state_key: str,
    spent: float,
    cap: float,
    session_id: str,
    group_id: str,
    last_call_cost: float,
    owner_account_id: Optional[str],
) -> None:
    del last_call_cost  # not included in fixed templates (keeps emails concise)
    if cap <= 0:
        return
    ratio = spent / cap
    cap_warn_ratio = default_alert_cap_warn_ratio()
    if ratio < cap_warn_ratio:
        return

    budget_type, budget_id, _short = _scope_labels(state_key)
    pct = ratio * 100.0
    owner_email = _account_email(owner_account_id) if owner_account_id else None

    with _state_lock:
        entry = state.setdefault(state_key, {"warn_sent": False, "critical_sent": False})
        researcher, ops = _recipients_for_scope(owner_account_id)

        if ratio >= 1.0 and not entry.get("critical_sent"):
            if researcher:
                _send_email(
                    CAP_LEVEL2_RESEARCHER_SUBJECT,
                    _cap_body_researcher(
                        level=2,
                        budget_type=budget_type,
                        budget_id=budget_id,
                        spent=spent,
                        cap=cap,
                        pct=pct,
                        session_id=session_id,
                        group_id=group_id,
                    ),
                    researcher,
                )
            if ops:
                _send_email(
                    CAP_LEVEL2_OPS_SUBJECT,
                    _cap_body_ops(
                        level=2,
                        budget_type=budget_type,
                        budget_id=budget_id,
                        spent=spent,
                        cap=cap,
                        pct=pct,
                        session_id=session_id,
                        group_id=group_id,
                        owner_email=owner_email,
                    ),
                    ops,
                )
            entry["critical_sent"] = True
            entry["warn_sent"] = True

        elif ratio >= cap_warn_ratio and not entry.get("warn_sent"):
            if researcher:
                _send_email(
                    CAP_LEVEL1_RESEARCHER_SUBJECT,
                    _cap_body_researcher(
                        level=1,
                        budget_type=budget_type,
                        budget_id=budget_id,
                        spent=spent,
                        cap=cap,
                        pct=pct,
                        session_id=session_id,
                        group_id=group_id,
                    ),
                    researcher,
                )
            if ops:
                _send_email(
                    CAP_LEVEL1_OPS_SUBJECT,
                    _cap_body_ops(
                        level=1,
                        budget_type=budget_type,
                        budget_id=budget_id,
                        spent=spent,
                        cap=cap,
                        pct=pct,
                        session_id=session_id,
                        group_id=group_id,
                        owner_email=owner_email,
                    ),
                    ops,
                )
            entry["warn_sent"] = True

        state[state_key] = entry
        _save_alert_state(state)


def maybe_send_cap_threshold_alerts(
    rollups: Dict[str, Any],
    *,
    session_id: str,
    group_id: str,
    cost_usd: float,
) -> None:
    if not _cap_alerts_enabled():
        return

    from usage_tracker import (
        default_session_spend_cap_usd,
        get_account_spend_usd,
        get_group_spend_usd,
        get_session_spend_usd,
        resolve_group_spend_cap,
    )
    from match_manager import match_manager

    session = match_manager.get_session(session_id) if session_id else None
    owner_id = (
        str(getattr(session, "owner_account_id", "")).strip()
        if session and getattr(session, "owner_account_id", None)
        else None
    ) or None

    group_info = (
        match_manager.get_group_info(session_id, group_id)
        if session_id and group_id
        else None
    )

    state = _load_alert_state()

    if group_id:
        _evaluate_cap_scope(
            state,
            f"group:{group_id}",
            get_group_spend_usd(group_id),
            resolve_group_spend_cap(session_id, group_id, group_info),
            session_id,
            group_id,
            cost_usd,
            owner_id,
        )

    if session_id:
        s_cap = default_session_spend_cap_usd()
        if s_cap is not None:
            _evaluate_cap_scope(
                state,
                f"session:{session_id}",
                get_session_spend_usd(session_id),
                s_cap,
                session_id,
                group_id,
                cost_usd,
                owner_id,
            )

    if owner_id:
        from account_store import get_account

        acct = get_account(owner_id)
        if acct:
            _evaluate_cap_scope(
                state,
                f"account:{owner_id}",
                get_account_spend_usd(owner_id),
                float(acct.get("spend_cap_usd") or default_account_spend_cap_usd()),
                session_id,
                group_id,
                cost_usd,
                owner_id,
            )


def maybe_send_usage_alerts(
    rollups: Dict[str, Any],
    *,
    group_id: str,
    session_id: str,
    cost_usd: float,
) -> None:
    if not _alert_enabled():
        return

    global _last_burst_alert_at
    hourly_threshold = default_alert_hourly_spend_usd()
    group_burst_threshold = default_alert_group_burst_usd()

    hour_key = datetime.now().strftime("%Y-%m-%dT%H")
    hour_spend = float(rollups.get("hourly", {}).get(hour_key, {}).get("spend_usd", 0))
    group_spend = float(rollups.get("groups", {}).get(group_id, {}).get("spend_usd", 0))

    reasons = []
    if hour_spend >= hourly_threshold:
        reasons.append(
            f"Hourly platform spend ${hour_spend:.2f} USD (threshold ${hourly_threshold:.2f} USD)"
        )
    if group_spend >= group_burst_threshold:
        reasons.append(
            f"Chat group {group_id} total ${group_spend:.2f} USD "
            f"(threshold ${group_burst_threshold:.2f} USD)"
        )

    if not reasons:
        return

    with _burst_lock:
        now = datetime.now()
        if _last_burst_alert_at and now - _last_burst_alert_at < timedelta(
            minutes=default_alert_cooldown_minutes()
        ):
            return
        _last_burst_alert_at = now

    _send_email(
        BURST_OPS_SUBJECT,
        _burst_body_ops(
            session_id=session_id,
            group_id=group_id,
            last_call_cost=cost_usd,
            reasons=reasons,
            at=now,
        ),
        _ops_recipients(),
    )
