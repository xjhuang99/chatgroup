"""Shared runtime state for group chat (locks, templates)."""

import asyncio
from datetime import datetime
from typing import Dict

from fastapi.templating import Jinja2Templates

from match_manager import match_manager

templates = Jinja2Templates(directory="templates")

group_locks: Dict[str, asyncio.Lock] = {}
DEFAULT_IDLE_THRESHOLD = 20


def get_group_lock(group_id: str) -> asyncio.Lock:
    if group_id not in group_locks:
        group_locks[group_id] = asyncio.Lock()
    return group_locks[group_id]


def touch_group_activity(session_id: str, group_id: str) -> None:
    group_info = match_manager.get_group_info(session_id, group_id)
    if group_info is not None:
        group_info["last_activity"] = datetime.now()
