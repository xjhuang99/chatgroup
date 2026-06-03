"""
Central shutdown when a group chat ends — stops bots, queues, timers, and idle nudges.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from match_manager import MatchManager


def shutdown_group_chat(
    match_manager: "MatchManager",
    session_id: str,
    group_id: str,
    *,
    end_group: bool = True,
) -> None:
    from bot_manager import remove_room_bots
    from bot_queue import bot_response_queue
    from group_idle import shutdown_group_idle
    from session_runtime import cancel_turn_timer

    shutdown_group_idle(match_manager, session_id, group_id)
    cancel_turn_timer(session_id, group_id)
    bot_response_queue.cancel_room(group_id)
    remove_room_bots(group_id)
    if end_group:
        match_manager.end_group(session_id, group_id)
