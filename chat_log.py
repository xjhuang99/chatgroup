"""
Per-room research chat log (JSONL): prompts, orchestration, usage, lifecycle.
Used for Qualtrics "full" export and Dashboard research_log CSV — not shown in live chat UI.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

CHAT_LOG_DIR = os.path.join("config", "chat_logs")
_turn_counters: Dict[str, int] = {}


def research_log_raw_output_enabled() -> bool:
    return os.getenv("RESEARCH_LOG_RAW_OUTPUT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _log_path(group_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (group_id or "room"))
    return os.path.join(CHAT_LOG_DIR, f"{safe}.jsonl")


def new_request_id() -> str:
    return f"req-{uuid.uuid4().hex[:12]}"


def next_turn_id(group_id: str) -> str:
    n = _turn_counters.get(group_id, 0) + 1
    _turn_counters[group_id] = n
    return f"T{n}"


def append_chat_log_event(
    session_id: str,
    group_id: str,
    event_type: str,
    details: Optional[Dict[str, Any]] = None,
    *,
    actor: Optional[str] = None,
) -> None:
    os.makedirs(CHAT_LOG_DIR, exist_ok=True)
    row = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "group_id": group_id,
        "event_type": event_type,
        "actor": actor,
        "details": details or {},
    }
    try:
        with open(_log_path(group_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"⚠️ chat_log write failed: {e}")


def _clip(text: str, n: int = 800) -> str:
    t = (text or "").strip()
    if len(t) <= n:
        return t
    return t[:n] + "…"


MAX_LOG_FIELD_CHARS = 50_000


def serialize_llm_messages(messages: Optional[List[Dict]]) -> Dict[str, Any]:
    """Flatten OpenAI-style messages for research log / full transcript export."""
    if not messages:
        return {}
    system_blocks: List[str] = []
    user_blocks: List[str] = []
    assistant_blocks: List[str] = []
    for m in messages:
        role = m.get("role", "")
        content = str(m.get("content", "") or "")
        if role == "system":
            system_blocks.append(content)
        elif role == "user":
            user_blocks.append(content)
        elif role == "assistant":
            assistant_blocks.append(content)
    full_system = "\n\n---\n\n".join(system_blocks)
    return {
        "system_prompt_full": _clip(full_system, MAX_LOG_FIELD_CHARS),
        "system_block_count": len(system_blocks),
        "user_message": _clip(user_blocks[-1] if user_blocks else "", 4000),
        "assistant_message": _clip(assistant_blocks[-1] if assistant_blocks else "", 2000),
    }


def log_llm_call(
    session_id: str,
    group_id: str,
    event_type: str,
    *,
    actor: Optional[str] = None,
    messages: Optional[List[Dict]] = None,
    system_prompt_full: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """Append LLM request row; returns request_id for pairing with response/usage."""
    details: Dict[str, Any] = dict(extra or {})
    request_id = details.get("request_id") or new_request_id()
    details["request_id"] = request_id
    if messages:
        details.update(serialize_llm_messages(messages))
    elif system_prompt_full:
        details["system_prompt_full"] = _clip(system_prompt_full, MAX_LOG_FIELD_CHARS)
    append_chat_log_event(session_id, group_id, event_type, details, actor=actor)
    return request_id


def log_llm_response(
    session_id: str,
    group_id: str,
    *,
    request_id: str,
    actor: str,
    reply: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    details: Dict[str, Any] = {
        "request_id": request_id,
        "reply": _clip(reply or "", 8000),
    }
    if extra:
        details.update(extra)
    raw = details.get("raw_model_output")
    if raw and not research_log_raw_output_enabled():
        details.pop("raw_model_output", None)
    append_chat_log_event(session_id, group_id, "llm_response", details, actor=actor)


def log_api_usage(
    session_id: str,
    group_id: str,
    request_id: str,
    *,
    model: str,
    call_type: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    latency_ms: float,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    details: Dict[str, Any] = {
        "request_id": request_id,
        "model": model,
        "call_type": call_type,
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "cost_usd": round(float(cost_usd), 6),
        "latency_ms": round(float(latency_ms), 1),
    }
    if extra:
        details.update(extra)
    append_chat_log_event(session_id, group_id, "api_usage", details)


def log_llm_error(
    session_id: str,
    group_id: str,
    *,
    request_id: Optional[str] = None,
    actor: Optional[str] = None,
    error_type: str,
    message: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    details: Dict[str, Any] = {
        "error_type": error_type,
        "message": _clip(message, 2000),
    }
    if request_id:
        details["request_id"] = request_id
    if extra:
        details.update(extra)
    append_chat_log_event(session_id, group_id, "llm_error", details, actor=actor)


def log_orchestrate(
    session_id: str,
    group_id: str,
    *,
    turn_id: str,
    trigger_sender: str,
    trigger_kind: str,
    chain_depth: int,
    session_mode: int,
    bots_eligible: List[str],
    bots_queued: List[str],
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    details: Dict[str, Any] = {
        "turn_id": turn_id,
        "trigger_sender": trigger_sender,
        "trigger_kind": trigger_kind,
        "chain_depth": chain_depth,
        "session_mode": session_mode,
        "bots_eligible": bots_eligible,
        "bots_queued": bots_queued,
        "bot_count_queued": len(bots_queued),
    }
    if extra:
        details.update(extra)
    event_type = "orchestrate_empty" if not bots_queued else "orchestrate"
    append_chat_log_event(
        session_id, group_id, event_type, details, actor=trigger_sender
    )


def log_group_created(
    session_id: str,
    group_id: str,
    *,
    members: List[str],
    member_names: Dict[str, str],
    condition: Optional[str] = None,
) -> None:
    append_chat_log_event(
        session_id,
        group_id,
        "group_created",
        {
            "members": list(members or []),
            "member_names": dict(member_names or {}),
            "condition": condition,
        },
    )


def log_participant_join(
    session_id: str,
    group_id: str,
    *,
    uid: str,
    display_name: str,
    member_names: Dict[str, str],
) -> None:
    append_chat_log_event(
        session_id,
        group_id,
        "participant_join",
        {
            "uid": uid,
            "display_name": display_name,
            "member_names": dict(member_names or {}),
        },
        actor=display_name,
    )


def log_ai_opening(
    session_id: str,
    group_id: str,
    *,
    bot_name: str,
    text: str,
    delay_seconds: float,
) -> None:
    append_chat_log_event(
        session_id,
        group_id,
        "ai_opening",
        {
            "bot_name": bot_name,
            "text": text,
            "delay_seconds": delay_seconds,
        },
        actor=bot_name,
    )


def log_session_ended(
    session_id: str,
    group_id: str,
    *,
    reason: str,
    duration_seconds: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    details: Dict[str, Any] = {"reason": reason}
    if duration_seconds is not None:
        details["duration_seconds"] = round(float(duration_seconds), 1)
    if extra:
        details.update(extra)
    append_chat_log_event(session_id, group_id, "session_ended", details)


def log_room_pause_state(
    session_id: str,
    group_id: str,
    *,
    paused: bool,
) -> None:
    append_chat_log_event(
        session_id,
        group_id,
        "room_resumed" if not paused else "room_paused",
        {"paused": paused},
    )


def log_context_bump(
    session_id: str,
    group_id: str,
    *,
    context_version: int,
    sender: str,
    text_preview: str,
) -> None:
    append_chat_log_event(
        session_id,
        group_id,
        "context_bump",
        {
            "context_version": context_version,
            "sender": sender,
            "text_preview": _clip(text_preview, 300),
        },
        actor=sender,
    )


def log_mode4_timing(
    session_id: str,
    group_id: str,
    *,
    bot_name: str,
    request_id: Optional[str],
    turn_id: Optional[str],
    pre_delay_sec: float,
    rethink_sec: Optional[float] = None,
    attempt: int = 1,
) -> None:
    details: Dict[str, Any] = {
        "attempt": attempt,
        "pre_delay_sec": round(pre_delay_sec, 2),
    }
    if rethink_sec is not None:
        details["rethink_sec"] = round(rethink_sec, 2)
    if request_id:
        details["request_id"] = request_id
    if turn_id:
        details["turn_id"] = turn_id
    append_chat_log_event(
        session_id, group_id, "mode4_timing", details, actor=bot_name
    )


def load_chat_log_events(group_id: str, limit: int = 50_000) -> List[Dict]:
    path = _log_path(group_id)
    if not os.path.exists(path):
        return []
    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"⚠️ chat_log read failed: {e}")
        return []
    return events[-limit:]


async def build_research_chat_log_text(
    group_id: str,
    messages: Optional[List[Dict]] = None,
) -> str:
    """Human-readable research log: events + chat lines (with DB notes)."""
    from session_runtime import build_transcript_text

    lines = ["=== ACTR RESEARCH CHAT LOG ===", f"room_id: {group_id}", ""]
    lines.append("--- System events (prompts, decisions, refreshes) ---")
    for ev in load_chat_log_events(group_id):
        ts = ev.get("timestamp", "")
        et = ev.get("event_type", "?")
        actor = ev.get("actor") or ""
        prefix = f"[{ts}] {et}"
        if actor:
            prefix += f" ({actor})"
        lines.append(prefix)
        details = ev.get("details") or {}
        for key, val in details.items():
            if val is None or val == "":
                continue
            if isinstance(val, (dict, list)):
                val = json.dumps(val, ensure_ascii=False)[:2000]
            else:
                val = str(val)
            if "\n" in val:
                lines.append(f"  {key}:")
                for sub in val.split("\n")[:30]:
                    lines.append(f"    {sub}")
            else:
                lines.append(f"  {key}: {_clip(val, 1200)}")
        lines.append("")

    lines.append("--- Chat transcript (visible messages + export notes) ---")
    if messages is not None:
        for m in messages:
            ts = m.get("timestamp", "")
            lines.append(f"[{ts}] {m.get('sender', '?')}: {m.get('text', '')}")
            note = (m.get("note") or "").strip()
            if note:
                lines.append(f"           {note}")
    else:
        lines.append(await build_transcript_text(group_id))

    return "\n".join(lines).strip() + "\n"


def resolve_qualtrics_export_text(
    session,
    transcript_text: str,
    research_log_text: str,
) -> str:
    mode = (getattr(session, "qualtrics_log_mode", None) or "transcript").strip().lower()
    if mode == "full":
        return research_log_text or transcript_text
    return transcript_text
