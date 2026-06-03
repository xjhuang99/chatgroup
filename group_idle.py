"""
Per-group idle nudge timers (补刀). Cancel when the group chat ends.
"""

from __future__ import annotations

import asyncio
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from match_manager import MatchManager

# task_key = "{session_id}_{group_id}"
group_idle_tasks: Dict[str, asyncio.Task] = {}


def cancel_group_idle_timer(session_id: str, group_id: str) -> None:
    """Stop pending idle nudge for this group."""
    task_key = f"{session_id}_{group_id}"
    task = group_idle_tasks.pop(task_key, None)
    if task and not task.done():
        task.cancel()


def is_group_chat_live(match_manager: "MatchManager", session_id: str, group_id: str) -> bool:
    """False after end_group or when marked ended (duration limit, admin delete)."""
    group_info = match_manager.get_group_info(session_id, group_id)
    if not group_info:
        return False
    return not group_info.get("ended", False)


def mark_group_ended(match_manager: "MatchManager", session_id: str, group_id: str) -> None:
    """Block new AI/idle work before active_rooms entry is removed."""
    group_info = match_manager.get_group_info(session_id, group_id)
    if group_info is not None:
        group_info["ended"] = True


def shutdown_group_idle(match_manager: "MatchManager", session_id: str, group_id: str) -> None:
    """Call when a group chat ends — no more idle nudges or AI for this room."""
    mark_group_ended(match_manager, session_id, group_id)
    cancel_group_idle_timer(session_id, group_id)
