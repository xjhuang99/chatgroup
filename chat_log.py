"""
Per-room research chat log (JSONL): prompts, persona mode 4 decisions, mode 4 refresh, skips.
Used for Qualtrics "full" export and Dashboard/debug — not shown in the live chat UI.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

CHAT_LOG_DIR = os.path.join("config", "chat_logs")


def _log_path(group_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (group_id or "room"))
    return os.path.join(CHAT_LOG_DIR, f"{safe}.jsonl")


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


def _clip(text: str, n: int = 800) -> str:
    t = (text or "").strip()
    if len(t) <= n:
        return t
    return t[:n] + "…"


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
