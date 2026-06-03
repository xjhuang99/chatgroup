"""
Activity Logger: records system events (messages, bots, rooms, sessions, config).
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum


class ActivityType(Enum):
    """Activity event types."""
    USER_MESSAGE = "user_message"
    BOT_RESPONSE = "bot_response"
    BOT_TRIGGERED = "bot_triggered"
    BOT_SKIPPED = "bot_skipped"
    SESSION_STARTED = "session_started"
    ERROR_OCCURRED = "error_occurred"


class Activity:
    """One activity log entry."""

    def __init__(
        self,
        activity_type: ActivityType,
        session_id: str,
        room_id: Optional[str] = None,
        actor: Optional[str] = None,
        details: Optional[Dict] = None,
    ):
        self.activity_type = activity_type.value
        self.timestamp = datetime.now().isoformat()
        self.session_id = session_id
        self.room_id = room_id
        self.actor = actor
        self.details = details or {}

    def to_dict(self) -> Dict:
        return {
            "event_type": self.activity_type,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "room_id": self.room_id,
            "actor": self.actor,
            "details": self.details,
        }


class ActivityLogger:
    """Persists activity to memory and JSONL files per session."""

    def __init__(self, log_dir: str = "activity_logs"):
        self.log_dir = log_dir
        self.activities: Dict[str, List[Activity]] = {}
        os.makedirs(log_dir, exist_ok=True)
        self._load_activities_from_disk()

    def log_activity(self, activity: Activity) -> str:
        session_id = activity.session_id
        if session_id not in self.activities:
            self.activities[session_id] = []
        self.activities[session_id].append(activity)
        self._save_activity_to_file(session_id, activity)
        return activity.timestamp

    def log_user_message(self, session_id: str, room_id: str, user_id: str, message: str):
        self.log_activity(
            Activity(
                ActivityType.USER_MESSAGE,
                session_id,
                room_id=room_id,
                actor=user_id,
                details={"message": message[:100]},
            )
        )

    def log_bot_response(self, session_id: str, room_id: str, bot_name: str, response: str, mode: int = 1):
        self.log_activity(
            Activity(
                ActivityType.BOT_RESPONSE,
                session_id,
                room_id=room_id,
                actor=bot_name,
                details={"response": response[:100], "mode": mode, "length": len(response)},
            )
        )

    def log_bot_triggered(self, session_id: str, room_id: str, bot_name: str):
        self.log_activity(
            Activity(ActivityType.BOT_TRIGGERED, session_id, room_id=room_id, actor=bot_name)
        )

    def log_bot_skipped(
        self,
        session_id: str,
        room_id: str,
        bot_name: str,
        reason: str = "skipped",
        extra: Optional[Dict] = None,
    ):
        details = {"reason": reason}
        if extra:
            details.update(extra)
        self.log_activity(
            Activity(
                ActivityType.BOT_SKIPPED,
                session_id,
                room_id=room_id,
                actor=bot_name,
                details=details,
            )
        )

    def log_session_started(self, session_id: str, session_name: str):
        self.log_activity(
            Activity(ActivityType.SESSION_STARTED, session_id, details={"session_name": session_name})
        )

    def log_error(self, session_id: str, error_id: str, context: str):
        self.log_activity(
            Activity(
                ActivityType.ERROR_OCCURRED,
                session_id,
                details={"error_id": error_id, "context": context},
            )
        )

    def get_session_activities(self, session_id: str) -> List[Dict]:
        if session_id not in self.activities:
            return []
        return [a.to_dict() for a in self.activities[session_id]]

    def get_recent_activities(self, session_id: str, limit: int = 50) -> List[Dict]:
        if session_id not in self.activities:
            return []
        activities = self.activities[session_id]
        return [a.to_dict() for a in activities[-limit:]]

    def _save_activity_to_file(self, session_id: str, activity: Activity):
        log_file = os.path.join(self.log_dir, f"{session_id}_activity.jsonl")
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(activity.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"⚠️ Failed to save activity: {e}")

    @staticmethod
    def _activity_from_persisted(data: Dict) -> Activity:
        """Rebuild Activity from JSONL (disk uses event_type in to_dict output)."""
        activity = Activity.__new__(Activity)
        activity.__dict__.update(data)
        if not getattr(activity, "activity_type", None):
            activity.activity_type = data.get("event_type") or data.get("activity_type") or "unknown"
        return activity

    def _load_activities_from_disk(self):
        for filename in os.listdir(self.log_dir):
            if filename.endswith("_activity.jsonl"):
                session_id = filename.replace("_activity.jsonl", "")
                log_file = os.path.join(self.log_dir, filename)
                try:
                    activities = []
                    with open(log_file, "r", encoding="utf-8") as f:
                        for line in f:
                            data = json.loads(line)
                            activities.append(self._activity_from_persisted(data))
                    if activities:
                        self.activities[session_id] = activities
                except Exception as e:
                    print(f"⚠️ Failed to load activities: {e}")


activity_logger = ActivityLogger()
