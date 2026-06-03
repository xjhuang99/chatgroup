#!/usr/bin/env python3
"""
Remove all chat groups and message history. Keeps session definitions in config/sessions.json.

Usage (from repo root):
  python3 scripts/purge_groups_history.py

Restart the ACTR server afterward if it is already running.
"""

import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


async def main() -> None:
    from context_manager import conversation_contexts
    from db.database import wipe_all_chat_history
    from group_lifecycle import shutdown_group_chat
    from match_manager import PARTICIPANT_INDEX_FILE, match_manager

    removed_rooms = []
    for session_id, groups in list(match_manager.active_rooms.items()):
        for group_id in list(groups.keys()):
            shutdown_group_chat(match_manager, session_id, group_id, end_group=True)
            removed_rooms.append(group_id)
        match_manager.active_rooms[session_id] = {}

    for sid in list(match_manager.sessions.keys()):
        match_manager.forming_fifo[sid] = []
        match_manager.forming_stratified[sid] = {}

    match_manager.user_locations.clear()
    match_manager.participant_groups.clear()
    match_manager.save_participant_index()

    msg_count = await wipe_all_chat_history()
    conversation_contexts.clear()

    chat_log_dir = os.path.join(ROOT, "config", "chat_logs")
    log_files = 0
    if os.path.isdir(chat_log_dir):
        for name in os.listdir(chat_log_dir):
            path = os.path.join(chat_log_dir, name)
            if os.path.isfile(path):
                os.remove(path)
                log_files += 1

    activity_dir = os.path.join(ROOT, "activity_logs")
    activity_files = 0
    if os.path.isdir(activity_dir):
        for name in os.listdir(activity_dir):
            path = os.path.join(activity_dir, name)
            if os.path.isfile(path):
                os.remove(path)
                activity_files += 1

    print("✅ Purge complete (sessions kept).")
    print(f"   Active groups removed from memory: {len(removed_rooms)}")
    if removed_rooms:
        print(f"   Group IDs: {', '.join(removed_rooms[:20])}{'…' if len(removed_rooms) > 20 else ''}")
    print(f"   DB messages deleted: {msg_count}")
    print(f"   Research chat_logs removed: {log_files}")
    print(f"   Activity log files removed: {activity_files}")
    print("   participant_index.json cleared")
    if removed_rooms == [] and msg_count == 0:
        print("   (No in-memory groups; DB may still have been wiped.)")
    print("\n⚠️  If uvicorn/main.py is running, restart it so Dashboard Monitor is empty.")


if __name__ == "__main__":
    asyncio.run(main())
