import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from study_conditions import assign_group_disclosure
from human_defaults import HUMAN_LIKE_SESSION, MODE_4_SESSION_DEFAULTS, apply_human_session_defaults
from usage_tracker import default_group_spend_cap_usd

PARTICIPANT_INDEX_FILE = "config/participant_index.json"


def _sync_active_group_spend_caps(session_id: str, cap_usd: float, active_rooms: Dict) -> None:
    """Apply session spend cap to groups already in memory (frozen cap at create time)."""
    cap = max(0.5, float(cap_usd))
    for info in active_rooms.get(session_id, {}).values():
        info["spend_cap_usd"] = cap


def resolve_human_group_bounds(session) -> tuple:
    """
    (min_humans, max_humans) per group for matching.
    Legacy sessions only have group_size → fixed min=max=group_size.
    """
    gs = max(1, int(getattr(session, "group_size", 1) or 1))
    min_h = getattr(session, "min_humans_per_group", None)
    max_h = getattr(session, "max_humans_per_group", None)
    if min_h is None and max_h is None:
        return gs, gs
    if min_h is None:
        min_h = gs
    if max_h is None:
        max_h = gs
    min_h = max(1, min(int(min_h), 20))
    max_h = max(min_h, min(int(max_h), 20))
    return min_h, max_h


def normalize_human_group_bounds(
    group_size: Optional[int] = None,
    min_humans: Optional[int] = None,
    max_humans: Optional[int] = None,
) -> tuple:
    """Return (min_h, max_h); group_size sets both when min/max omitted."""
    if min_humans is not None or max_humans is not None:
        mn = max(1, int(min_humans if min_humans is not None else (max_humans or 1)))
        mx = max(mn, int(max_humans if max_humans is not None else mn))
        return min(mn, 20), min(mx, 20)
    gs = max(1, min(int(group_size or 1), 20))
    return gs, gs


def _apply_human_bounds_to_session(session, min_h: int, max_h: int) -> None:
    session.min_humans_per_group = min_h
    session.max_humans_per_group = max_h
    session.group_size = max_h


def _sync_active_room_bot_concurrency(session_id: str, session, active_rooms: Dict) -> None:
    from bot_queue import bot_response_queue

    mode = int(getattr(session, "session_mode", 1) or 1)
    n = max(1, len(session.bots)) if mode == 4 and session.bots else 1
    for gid in active_rooms.get(session_id, {}):
        bot_response_queue.set_room_concurrency(gid, n)


class SessionConfig:
    """
    Configuration for a specific experimental Session.
    """
    def __init__(self, session_id: str, name: str, group_size: int = 1, bot_enabled: bool = True):
        self.session_id = session_id
        self.name = name
        self.group_size = group_size
        self.bot_enabled = bot_enabled
        self.bots = []
        self.history_limit = 10000
        self.created_at = datetime.now()
        self.participant_names = []
        # Survey open for N days; each group chat lasts M minutes (from group formation)
        self.survey_open_days = 7
        self.group_chat_duration_minutes = 3
        # Qualtrics integration (optional)
        self.qualtrics_handoff_enabled = True
        self.qualtrics_store_chat = True
        self.qualtrics_field_transcript = "transcript"
        self.qualtrics_field_status = "chat_status"
        self.turn_duration_seconds = 60
        # Matching
        self.assignment_mode = "fifo"  # fifo | stratified
        self.condition_enabled = True
        self.style_mimic_target = "c"
        self.owner_account_id = None
        apply_human_session_defaults(self)
        self.group_spend_cap_usd = default_group_spend_cap_usd()
        mn, mx = normalize_human_group_bounds(group_size=self.group_size)
        self.min_humans_per_group = mn
        self.max_humans_per_group = mx

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "name": self.name,
            "group_size": self.group_size,
            "min_humans_per_group": getattr(self, "min_humans_per_group", self.group_size),
            "max_humans_per_group": getattr(self, "max_humans_per_group", self.group_size),
            "bot_enabled": self.bot_enabled,
            "bots": self.bots,
            "history_limit": self.history_limit,
            "created_at": self.created_at.isoformat(),
            "participant_names": self.participant_names,
            "session_mode": self.session_mode,
            "survey_open_days": self.survey_open_days,
            "group_chat_duration_minutes": self.group_chat_duration_minutes,
            "qualtrics_handoff_enabled": self.qualtrics_handoff_enabled,
            "qualtrics_store_chat": self.qualtrics_store_chat,
            "qualtrics_field_transcript": self.qualtrics_field_transcript,
            "qualtrics_field_status": self.qualtrics_field_status,
            "ai_starts_conversation": self.ai_starts_conversation,
            "turn_mode": self.turn_mode,
            "turn_duration_seconds": self.turn_duration_seconds,
            "assignment_mode": self.assignment_mode,
            "condition_enabled": self.condition_enabled,
            "style_mimic_enabled": self.style_mimic_enabled,
            "style_mimic_target": self.style_mimic_target,
            "bot_reply_on_any_message": self.bot_reply_on_any_message,
            "max_chain_depth": self.max_chain_depth,
            "use_mentions": self.use_mentions,
            "mention_prob": self.mention_prob,
            "self_correction_prob": self.self_correction_prob,
            "group_spend_cap_usd": getattr(self, "group_spend_cap_usd", default_group_spend_cap_usd()),
            "owner_account_id": getattr(self, "owner_account_id", None),
            "parallel_start_jitter_sec": getattr(self, "parallel_start_jitter_sec", MODE_4_SESSION_DEFAULTS["parallel_start_jitter_sec"]),
            "rethink_seconds": getattr(self, "rethink_seconds", MODE_4_SESSION_DEFAULTS["rethink_seconds"]),
            "max_refresh_attempts": getattr(self, "max_refresh_attempts", MODE_4_SESSION_DEFAULTS["max_refresh_attempts"]),
            "qualtrics_log_mode": getattr(self, "qualtrics_log_mode", "transcript"),
        }

    @classmethod
    def from_dict(cls, data: Dict):
        obj = cls(
            session_id=data.get("session_id", f"SES-{uuid.uuid4().hex[:5].upper()}"),
            name=data.get("name", "Unnamed Session"),
            group_size=data.get("group_size", 1),
            bot_enabled=data.get("bot_enabled", True),
        )
        obj.bots = data.get("bots", [])
        obj.history_limit = max(100, min(int(data.get("history_limit", 10000)), 50000))
        obj.participant_names = data.get("participant_names", [])
        obj.session_mode = data.get("session_mode", HUMAN_LIKE_SESSION["session_mode"])
        obj.survey_open_days = max(1, min(int(data.get("survey_open_days", 7)), 90))
        gcm = data.get("group_chat_duration_minutes")
        if gcm is not None:
            obj.group_chat_duration_minutes = max(1, min(int(gcm), 180))
        else:
            # Legacy group_timeout was inactivity minutes — default 3 min per-group chat
            obj.group_chat_duration_minutes = 3
        obj.qualtrics_handoff_enabled = data.get("qualtrics_handoff_enabled", False)
        obj.qualtrics_store_chat = data.get("qualtrics_store_chat", False)
        obj.qualtrics_field_transcript = data.get("qualtrics_field_transcript", "chat_transcript")
        obj.qualtrics_field_status = data.get("qualtrics_field_status", "chat_status")
        obj.ai_starts_conversation = data.get(
            "ai_starts_conversation", HUMAN_LIKE_SESSION["ai_starts_conversation"]
        )
        obj.turn_mode = data.get("turn_mode", "none")
        obj.turn_duration_seconds = data.get("turn_duration_seconds", 60)
        obj.assignment_mode = data.get("assignment_mode", "fifo")
        obj.condition_enabled = bool(data.get("condition_enabled", True))
        obj.style_mimic_enabled = bool(data.get("style_mimic_enabled", False))
        obj.style_mimic_target = str(data.get("style_mimic_target") or "c").strip() or "c"
        obj.bot_reply_on_any_message = bool(
            data.get("bot_reply_on_any_message", HUMAN_LIKE_SESSION["bot_reply_on_any_message"])
        )
        obj.max_chain_depth = max(
            1, min(int(data.get("max_chain_depth", HUMAN_LIKE_SESSION["max_chain_depth"])), 10)
        )
        obj.use_mentions = bool(data.get("use_mentions", HUMAN_LIKE_SESSION["use_mentions"]))
        obj.mention_prob = max(
            0.0, min(1.0, float(data.get("mention_prob", HUMAN_LIKE_SESSION["mention_prob"])))
        )
        obj.self_correction_prob = max(
            0.0,
            min(1.0, float(data.get("self_correction_prob", HUMAN_LIKE_SESSION["self_correction_prob"]))),
        )
        obj.group_spend_cap_usd = max(
            0.5,
            float(data.get("group_spend_cap_usd", default_group_spend_cap_usd())),
        )
        mn, mx = normalize_human_group_bounds(
            group_size=data.get("group_size"),
            min_humans=data.get("min_humans_per_group"),
            max_humans=data.get("max_humans_per_group"),
        )
        _apply_human_bounds_to_session(obj, mn, mx)
        raw_owner = data.get("owner_account_id")
        obj.owner_account_id = str(raw_owner).strip() if raw_owner else None
        m4 = MODE_4_SESSION_DEFAULTS
        obj.parallel_start_jitter_sec = max(
            0.0, min(float(data.get("parallel_start_jitter_sec", m4["parallel_start_jitter_sec"])), 30.0)
        )
        obj.rethink_seconds = max(
            0.0, min(float(data.get("rethink_seconds", m4["rethink_seconds"])), 30.0)
        )
        obj.max_refresh_attempts = max(
            1, min(int(data.get("max_refresh_attempts", m4["max_refresh_attempts"])), 10)
        )
        qlm = (data.get("qualtrics_log_mode") or "transcript").strip().lower()
        obj.qualtrics_log_mode = qlm if qlm in ("transcript", "full") else "transcript"
        if "created_at" in data:
            try:
                obj.created_at = datetime.fromisoformat(data["created_at"])
            except ValueError:
                pass
        return obj


class MatchManager:
    def __init__(self):
        self.sessions: Dict[str, SessionConfig] = {}
        self.active_rooms: Dict[str, Dict[str, Dict]] = {}
        # Each entry is a list of partial groups: [[uid,...], [uid,...]]
        self.forming_fifo: Dict[str, List[List[str]]] = {}
        self.forming_stratified: Dict[str, Dict[str, List[List[str]]]] = {}
        self.user_locations: Dict[str, Dict[str, str]] = {}
        self.participant_groups: Dict[str, Dict[str, str]] = {}
        self.load_all_sessions()
        self.load_participant_index()

    def load_participant_index(self):
        os.makedirs("config", exist_ok=True)
        if os.path.exists(PARTICIPANT_INDEX_FILE):
            try:
                with open(PARTICIPANT_INDEX_FILE, "r", encoding="utf-8") as f:
                    self.participant_groups = json.load(f)
            except Exception as e:
                print(f"⚠️ Failed to load participant index: {e}")
                self.participant_groups = {}

    def save_participant_index(self):
        os.makedirs("config", exist_ok=True)
        try:
            with open(PARTICIPANT_INDEX_FILE, "w", encoding="utf-8") as f:
                json.dump(self.participant_groups, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"❌ Failed to save participant index: {e}")

    def record_participant_group(self, session_id: str, uid: str, group_id: str):
        if session_id not in self.participant_groups:
            self.participant_groups[session_id] = {}
        self.participant_groups[session_id][uid] = group_id
        self.save_participant_index()

    def get_participant_group_id(self, session_id: str, uid: str) -> Optional[str]:
        if uid in self.user_locations and self.user_locations[uid].get("session_id") == session_id:
            return self.user_locations[uid].get("group_id")
        return self.participant_groups.get(session_id, {}).get(uid)

    @staticmethod
    def resolve_history_limit(session: Optional["SessionConfig"]) -> int:
        if not session:
            return 10000
        return max(100, min(int(getattr(session, "history_limit", 10000) or 10000), 50000))

    def participant_can_access_group(self, session_id: str, group_id: str, participant_id: str) -> bool:
        if not participant_id:
            return False
        if self.get_participant_group_id(session_id, participant_id) == group_id:
            return True
        group_info = self.get_group_info(session_id, group_id)
        if group_info and participant_id in group_info.get("members", []):
            return True
        loc = self.user_locations.get(participant_id)
        return bool(
            loc
            and loc.get("session_id") == session_id
            and loc.get("group_id") == group_id
        )

    def can_websocket_join(self, session_id: str, group_id: str, uid: str) -> tuple:
        """Return (allowed, error_message)."""
        group_info = self.get_group_info(session_id, group_id)
        if not group_info:
            return False, "This chat group has ended or does not exist."
        if group_info.get("ended"):
            return False, "This chat session has ended."
        if uid in group_info.get("members", []):
            return True, ""
        loc = self.user_locations.get(uid)
        if loc and loc.get("session_id") == session_id and loc.get("group_id") == group_id:
            if uid not in group_info.get("members", []):
                group_info.setdefault("members", []).append(uid)
            return True, ""
        return False, "You are not assigned to this chat group."

    def load_all_sessions(self):
        os.makedirs("config", exist_ok=True)
        config_file = "config/sessions.json"
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for sid, sdata in data.items():
                        self.sessions[sid] = SessionConfig.from_dict(sdata)
                        self.active_rooms[sid] = {}
                        self.forming_fifo[sid] = []
                        self.forming_stratified[sid] = {}
                print(f"✅ Loaded {len(self.sessions)} experimental sessions from config.")
            except Exception as e:
                print(f"⚠️ Failed to load sessions config: {e}")

    def save_all_sessions(self) -> bool:
        os.makedirs("config", exist_ok=True)
        config_file = "config/sessions.json"
        try:
            data = {sid: config.to_dict() for sid, config in self.sessions.items()}
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print("💾 Session configurations saved to disk.")
            return True
        except Exception as e:
            print(f"❌ Failed to save sessions: {e}")
            return False

    def create_session(
        self,
        name: str,
        group_size: int,
        bot_enabled: bool,
        bots: List,
        survey_open_days: int = 7,
        group_chat_duration_minutes: int = 3,
        participant_names: List = None,
        session_mode: int = None,
        qualtrics_handoff_enabled: bool = False,
        qualtrics_store_chat: bool = False,
        qualtrics_field_transcript: str = "chat_transcript",
        qualtrics_field_status: str = "chat_status",
        ai_starts_conversation: bool = None,
        turn_mode: str = None,
        turn_duration_seconds: int = 60,
        assignment_mode: str = "fifo",
        condition_enabled: bool = True,
        style_mimic_enabled: bool = None,
        style_mimic_target: str = "c",
        bot_reply_on_any_message: bool = None,
        max_chain_depth: int = None,
        use_mentions: bool = None,
        mention_prob: float = None,
        self_correction_prob: float = None,
        group_spend_cap_usd: float = None,
        min_humans_per_group: int = None,
        max_humans_per_group: int = None,
        owner_account_id: str = None,
        parallel_start_jitter_sec: float = None,
        rethink_seconds: float = None,
        max_refresh_attempts: int = None,
        qualtrics_log_mode: str = None,
    ) -> str:
        session_id = f"SES-{uuid.uuid4().hex[:5].upper()}"
        mn, mx = normalize_human_group_bounds(
            group_size=group_size,
            min_humans=min_humans_per_group,
            max_humans=max_humans_per_group,
        )
        config = SessionConfig(session_id, name, mx, bot_enabled)
        _apply_human_bounds_to_session(config, mn, mx)
        config.bots = bots
        config.survey_open_days = max(1, min(survey_open_days, 90))
        config.group_chat_duration_minutes = max(1, min(group_chat_duration_minutes, 180))
        config.participant_names = participant_names or []
        hs = HUMAN_LIKE_SESSION
        sm = session_mode if session_mode is not None else hs["session_mode"]
        sm = int(sm)
        if sm not in (1, 2, 3, 4):
            raise ValueError("session_mode must be 1, 2, 3, or 4")
        config.session_mode = sm
        config.qualtrics_handoff_enabled = qualtrics_handoff_enabled
        config.qualtrics_store_chat = qualtrics_store_chat
        config.qualtrics_field_transcript = qualtrics_field_transcript
        config.qualtrics_field_status = qualtrics_field_status
        config.ai_starts_conversation = (
            ai_starts_conversation if ai_starts_conversation is not None else hs["ai_starts_conversation"]
        )
        tm = turn_mode if turn_mode is not None else hs["turn_mode"]
        config.turn_mode = tm if tm in ("none", "round_robin", "timed") else "none"
        config.turn_duration_seconds = max(10, turn_duration_seconds)
        config.condition_enabled = bool(condition_enabled)
        if config.condition_enabled:
            config.assignment_mode = "stratified"
        else:
            config.assignment_mode = assignment_mode if assignment_mode in ("fifo", "stratified") else "fifo"
        config.style_mimic_enabled = (
            bool(style_mimic_enabled) if style_mimic_enabled is not None else hs["style_mimic_enabled"]
        )
        config.style_mimic_target = (style_mimic_target or "c").strip() or "c"
        config.bot_reply_on_any_message = (
            bool(bot_reply_on_any_message)
            if bot_reply_on_any_message is not None
            else hs["bot_reply_on_any_message"]
        )
        config.max_chain_depth = max(
            1,
            min(int(max_chain_depth if max_chain_depth is not None else hs["max_chain_depth"]), 10),
        )
        config.use_mentions = bool(use_mentions if use_mentions is not None else hs["use_mentions"])
        config.mention_prob = max(
            0.0, min(1.0, float(mention_prob if mention_prob is not None else hs["mention_prob"]))
        )
        config.self_correction_prob = max(
            0.0,
            min(
                1.0,
                float(
                    self_correction_prob
                    if self_correction_prob is not None
                    else hs["self_correction_prob"]
                ),
            ),
        )
        config.group_spend_cap_usd = max(
            0.5,
            float(
                group_spend_cap_usd
                if group_spend_cap_usd is not None
                else default_group_spend_cap_usd()
            ),
        )
        config.owner_account_id = str(owner_account_id).strip() if owner_account_id else None
        m4 = MODE_4_SESSION_DEFAULTS
        config.parallel_start_jitter_sec = max(
            0.0,
            min(
                float(
                    parallel_start_jitter_sec
                    if parallel_start_jitter_sec is not None
                    else m4["parallel_start_jitter_sec"]
                ),
                30.0,
            ),
        )
        config.rethink_seconds = max(
            0.0,
            min(
                float(rethink_seconds if rethink_seconds is not None else m4["rethink_seconds"]),
                30.0,
            ),
        )
        config.max_refresh_attempts = max(
            1,
            min(
                int(
                    max_refresh_attempts
                    if max_refresh_attempts is not None
                    else m4["max_refresh_attempts"]
                ),
                10,
            ),
        )
        qlm = (qualtrics_log_mode or "transcript").strip().lower()
        config.qualtrics_log_mode = qlm if qlm in ("transcript", "full") else "transcript"

        self.sessions[session_id] = config
        self.active_rooms[session_id] = {}
        self.forming_fifo[session_id] = []
        self.forming_stratified[session_id] = {}
        self.save_all_sessions()
        print(f"🎯 New Session Created: {session_id} ({name})")
        return session_id

    def get_session(self, session_id: str) -> Optional[SessionConfig]:
        return self.sessions.get(session_id)

    def is_session_open(self, session: SessionConfig) -> bool:
        """True while the session still accepts new participants (survey collection window)."""
        if not session:
            return False
        try:
            created = session.created_at
            if isinstance(created, str):
                created = datetime.fromisoformat(created)
        except (TypeError, ValueError):
            created = datetime.now()
        deadline = created + timedelta(days=max(1, session.survey_open_days))
        return datetime.now() < deadline

    def session_to_admin_dict(self, session: SessionConfig) -> Dict:
        return session.to_dict()

    def update_session(self, session_id: str, data: Dict) -> bool:
        session = self.sessions.get(session_id)
        if not session:
            return False
        if "session_name" in data and data["session_name"]:
            session.name = str(data["session_name"]).strip()
        if (
            "group_size" in data
            or "min_humans_per_group" in data
            or "max_humans_per_group" in data
        ):
            mn, mx = normalize_human_group_bounds(
                group_size=data.get("group_size", session.group_size),
                min_humans=data.get("min_humans_per_group", getattr(session, "min_humans_per_group", None)),
                max_humans=data.get("max_humans_per_group", getattr(session, "max_humans_per_group", None)),
            )
            _apply_human_bounds_to_session(session, mn, mx)
        if "bot_enabled" in data:
            session.bot_enabled = bool(data["bot_enabled"])
        if "bots" in data:
            session.bots = data["bots"]
        if "participant_names" in data:
            session.participant_names = data["participant_names"] or []
        if "history_limit" in data:
            session.history_limit = max(100, min(int(data["history_limit"]), 50000))
        if "session_mode" in data:
            sm = int(data["session_mode"])
            if sm not in (1, 2, 3, 4):
                raise ValueError("session_mode must be 1, 2, 3, or 4")
            session.session_mode = sm
            _sync_active_room_bot_concurrency(session_id, session, self.active_rooms)
        if "survey_open_days" in data:
            session.survey_open_days = max(1, min(int(data["survey_open_days"]), 90))
        if "group_chat_duration_minutes" in data:
            session.group_chat_duration_minutes = max(1, min(int(data["group_chat_duration_minutes"]), 180))
        if "qualtrics_handoff_enabled" in data:
            session.qualtrics_handoff_enabled = bool(data["qualtrics_handoff_enabled"])
        if "qualtrics_store_chat" in data:
            session.qualtrics_store_chat = bool(data["qualtrics_store_chat"])
        if "qualtrics_field_transcript" in data:
            session.qualtrics_field_transcript = str(data["qualtrics_field_transcript"] or "chat_transcript")
        if "qualtrics_field_status" in data:
            session.qualtrics_field_status = str(data["qualtrics_field_status"] or "chat_status")
        if "ai_starts_conversation" in data:
            session.ai_starts_conversation = bool(data["ai_starts_conversation"])
        if "turn_mode" in data:
            tm = data["turn_mode"]
            session.turn_mode = tm if tm in ("none", "round_robin", "timed") else "none"
        if "turn_duration_seconds" in data:
            session.turn_duration_seconds = max(10, int(data["turn_duration_seconds"]))
        if "condition_enabled" in data:
            session.condition_enabled = bool(data["condition_enabled"])
        if "assignment_mode" in data:
            am = data["assignment_mode"]
            session.assignment_mode = am if am in ("fifo", "stratified") else "fifo"
        if getattr(session, "condition_enabled", True):
            session.assignment_mode = "stratified"
        if "style_mimic_enabled" in data:
            session.style_mimic_enabled = bool(data["style_mimic_enabled"])
        if "style_mimic_target" in data:
            t = str(data["style_mimic_target"] or "").strip()
            if t:
                session.style_mimic_target = t
        if "bot_reply_on_any_message" in data:
            session.bot_reply_on_any_message = bool(data["bot_reply_on_any_message"])
        if "max_chain_depth" in data:
            session.max_chain_depth = max(1, min(int(data["max_chain_depth"]), 10))
        if "use_mentions" in data:
            session.use_mentions = bool(data["use_mentions"])
        if "mention_prob" in data:
            session.mention_prob = max(0.0, min(1.0, float(data["mention_prob"])))
        if "self_correction_prob" in data:
            session.self_correction_prob = max(
                0.0, min(1.0, float(data["self_correction_prob"]))
            )
        if "group_spend_cap_usd" in data:
            session.group_spend_cap_usd = max(0.5, float(data["group_spend_cap_usd"]))
            _sync_active_group_spend_caps(
                session_id, session.group_spend_cap_usd, self.active_rooms
            )
        if "parallel_start_jitter_sec" in data:
            session.parallel_start_jitter_sec = max(
                0.0, min(float(data["parallel_start_jitter_sec"]), 30.0)
            )
        if "rethink_seconds" in data:
            session.rethink_seconds = max(0.0, min(float(data["rethink_seconds"]), 30.0))
        if "max_refresh_attempts" in data:
            session.max_refresh_attempts = max(1, min(int(data["max_refresh_attempts"]), 10))
        if "qualtrics_log_mode" in data:
            qlm = str(data["qualtrics_log_mode"] or "transcript").strip().lower()
            session.qualtrics_log_mode = qlm if qlm in ("transcript", "full") else "transcript"
        return self.save_all_sessions()

    def get_all_sessions_summary(self, owner_account_id: Optional[str] = None) -> List[Dict]:
        summary = []
        for sid, config in self.sessions.items():
            if owner_account_id and getattr(config, "owner_account_id", None) != owner_account_id:
                continue
            active_groups = list(self.active_rooms.get(sid, {}).keys())
            summary.append({
                "id": sid,
                "name": config.name,
                "groups": active_groups,
                "group_size": config.group_size,
                "min_humans_per_group": getattr(config, "min_humans_per_group", config.group_size),
                "max_humans_per_group": getattr(config, "max_humans_per_group", config.group_size),
                "fixed_human_group_size": (
                    getattr(config, "min_humans_per_group", config.group_size)
                    == getattr(config, "max_humans_per_group", config.group_size)
                ),
                "bot_enabled": config.bot_enabled,
                "assignment_mode": config.assignment_mode,
                "survey_open_days": config.survey_open_days,
                "group_chat_duration_minutes": config.group_chat_duration_minutes,
                "is_open": self.is_session_open(config),
            })
        return summary

    def _normalize_condition(self, condition: Optional[str]) -> str:
        c = (condition or "").strip()
        return c if c else "_default"

    def add_to_queue(self, session_id: str, uid: str, condition: Optional[str] = None) -> Optional[str]:
        if session_id not in self.sessions:
            print(f"⚠️ Warning: Attempted to queue for invalid session {session_id}")
            return None

        session_config = self.sessions[session_id]
        if not self.is_session_open(session_config):
            print(f"🚫 Session {session_id} is closed (survey collection ended).")
            return None

        if not getattr(session_config, "condition_enabled", True):
            condition = None

        if uid in self.user_locations:
            return self.user_locations[uid].get("group_id")

        if getattr(session_config, "condition_enabled", True):
            return self._add_to_stratified_queue(session_id, uid, condition, session_config)
        if session_config.assignment_mode == "stratified":
            return self._add_to_stratified_queue(session_id, uid, condition, session_config)
        return self._add_to_fifo_queue(session_id, uid, session_config)

    def _assign_to_forming(
        self,
        forming: List[List[str]],
        uid: str,
        min_h: int,
        max_h: int,
    ) -> Optional[List[str]]:
        """
        Place uid in the first partial group with room (< max_h), or start a new group.
        When len >= min_h, remove that group from forming and return its member list.
        """
        slot: Optional[List[str]] = None
        for grp in forming:
            if uid in grp:
                slot = grp
                break
        if slot is None:
            for grp in forming:
                if len(grp) < max_h:
                    slot = grp
                    break
            if slot is None:
                slot = []
                forming.append(slot)
            if uid not in slot:
                slot.append(uid)

        if len(slot) >= min_h:
            forming.remove(slot)
            return list(slot[:max_h])
        return None

    def _add_to_fifo_queue(
        self, session_id: str, uid: str, session_config: SessionConfig,
    ) -> Optional[str]:
        min_h, max_h = resolve_human_group_bounds(session_config)
        forming = self.forming_fifo.setdefault(session_id, [])
        matched_members = self._assign_to_forming(forming, uid, min_h, max_h)
        waiting = sum(len(g) for g in forming)
        print(
            f"⏳ {uid} FIFO [{session_id}] forming_groups={len(forming)} "
            f"waiting_humans={waiting} (need {min_h}–{max_h} per group)"
        )
        if matched_members:
            group_id = f"GRP-{uuid.uuid4().hex[:4].upper()}"
            self.create_group(session_id, group_id, matched_members, condition=None)
            return group_id
        return None

    def _add_to_stratified_queue(
        self, session_id: str, uid: str, condition: Optional[str], session_config: SessionConfig
    ) -> Optional[str]:
        cond = self._normalize_condition(condition)
        min_h, max_h = resolve_human_group_bounds(session_config)
        buckets = self.forming_stratified.setdefault(session_id, {})
        forming = buckets.setdefault(cond, [])
        matched_members = self._assign_to_forming(forming, uid, min_h, max_h)
        waiting = sum(len(g) for g in forming)
        print(
            f"⏳ {uid} stratified [{session_id}] condition={cond} "
            f"forming_groups={len(forming)} waiting_humans={waiting} (need {min_h}–{max_h})"
        )
        if matched_members:
            group_id = f"GRP-{uuid.uuid4().hex[:4].upper()}"
            self.create_group(session_id, group_id, matched_members, condition=cond)
            return group_id
        return None

    def _count_forming_humans(self, forming: List[List[str]]) -> int:
        return sum(len(g) for g in forming)

    def count_waiting_participants(self, session_id: Optional[str] = None) -> int:
        """Humans in partial (not yet matched) groups."""
        if session_id is not None:
            n = self._count_forming_humans(self.forming_fifo.get(session_id, []))
            for forming in self.forming_stratified.get(session_id, {}).values():
                n += self._count_forming_humans(forming)
            return n
        n = sum(self._count_forming_humans(f) for f in self.forming_fifo.values())
        for buckets in self.forming_stratified.values():
            for forming in buckets.values():
                n += self._count_forming_humans(forming)
        return n

    def is_user_in_queue(self, session_id: str, uid: str) -> bool:
        return self._forming_slot_for_uid(session_id, uid) is not None

    def _forming_slot_for_uid(
        self, session_id: str, uid: str, condition: Optional[str] = None
    ) -> Optional[List[str]]:
        for grp in self.forming_fifo.get(session_id, []):
            if uid in grp:
                return grp
        buckets = self.forming_stratified.get(session_id, {})
        if condition is not None:
            forming = buckets.get(self._normalize_condition(condition), [])
            for grp in forming:
                if uid in grp:
                    return grp
        else:
            for forming in buckets.values():
                for grp in forming:
                    if uid in grp:
                        return grp
        return None

    def expected_human_display_names(self, session: SessionConfig) -> List[str]:
        """Full human roster labels for this session (including slots still waiting in queue)."""
        from participant_naming import (
            auto_letter_names,
            bot_reserved_names,
            participant_name_pool,
            uses_explicit_participant_names,
        )

        min_h, _ = resolve_human_group_bounds(session)
        pool = participant_name_pool(session, min_h)
        if len(pool) >= min_h:
            return list(pool[:min_h])
        if uses_explicit_participant_names(session):
            taken = set(pool) | bot_reserved_names(session)
            extra = auto_letter_names(taken, min_h - len(pool))
            return pool + extra
        return pool

    def get_queue_progress(
        self, session_id: str, uid: str, condition: Optional[str] = None
    ) -> Optional[Dict]:
        """Humans in the same forming group as uid (AI bots are not counted)."""
        session = self.sessions.get(session_id)
        slot = self._forming_slot_for_uid(session_id, uid, condition)
        if not session or slot is None:
            return None
        min_h, max_h = resolve_human_group_bounds(session)
        humans_matched = len(slot)
        ai_count = len(session.bots) if getattr(session, "bot_enabled", True) and session.bots else 0
        participants_needed = min_h + ai_count
        participants_matched = humans_matched + ai_count
        return {
            "humans_matched": humans_matched,
            "min_humans_per_group": min_h,
            "max_humans_per_group": max_h,
            "ai_teammates_ready": ai_count,
            "participants_matched": participants_matched,
            "participants_needed": participants_needed,
            "teammate_display_names": self.expected_human_display_names(session),
        }

    def _remove_uid_from_forming(self, forming: List[List[str]], uid: str) -> None:
        for grp in list(forming):
            if uid in grp:
                grp.remove(uid)
            if not grp:
                forming.remove(grp)

    def remove_from_queue(self, session_id: str, uid: str, condition: Optional[str] = None):
        self._remove_uid_from_forming(self.forming_fifo.get(session_id, []), uid)
        if session_id not in self.forming_stratified:
            return
        if condition is not None:
            cond = self._normalize_condition(condition)
            forming = self.forming_stratified[session_id].get(cond, [])
            self._remove_uid_from_forming(forming, uid)
            return
        for forming in self.forming_stratified[session_id].values():
            self._remove_uid_from_forming(forming, uid)

    def ensure_group_member_names(self, session_id: str, group_info: Dict) -> None:
        """Assign display names to all matched humans so roster APIs work before WebSocket join."""
        session = self.sessions.get(session_id)
        if not session:
            return
        from participant_naming import pick_human_display_name

        if "member_names" not in group_info:
            group_info["member_names"] = {}
        taken = set(group_info["member_names"].values())
        for uid in group_info.get("members") or []:
            if uid in group_info["member_names"]:
                taken.add(group_info["member_names"][uid])
                continue
            name = pick_human_display_name(session, taken)
            if name:
                group_info["member_names"][uid] = name
                taken.add(name)
            else:
                group_info["member_names"][uid] = uid

    def create_group(
        self, session_id: str, group_id: str, members: List[str] = None, condition: Optional[str] = None
    ):
        if session_id not in self.active_rooms:
            self.active_rooms[session_id] = {}

        if group_id not in self.active_rooms[session_id]:
            now = datetime.now()
            session_config = self.sessions.get(session_id)
            cap = default_group_spend_cap_usd()
            if session_config and getattr(session_config, "group_spend_cap_usd", None) is not None:
                cap = max(0.5, float(session_config.group_spend_cap_usd))
            group_info = {
                "members": members if members else [],
                "created_at": now,
                "last_activity": now,
                "condition": self._normalize_condition(condition) if condition else None,
                "opening_sent": False,
                "turn_initialized": False,
                "spend_cap_usd": cap,
                "context_version": 0,
                "last_context_bump_sender": None,
                "last_context_bump_text": "",
            }
            if session_config and session_config.bots and getattr(session_config, "condition_enabled", True):
                assign_group_disclosure(session_config.bots, condition, group_info)
            if members:
                self.ensure_group_member_names(session_id, group_info)
            self.active_rooms[session_id][group_id] = group_info
            if members:
                from chat_log import log_group_created

                log_group_created(
                    session_id,
                    group_id,
                    members=list(members),
                    member_names=dict(group_info.get("member_names", {})),
                    condition=group_info.get("condition"),
                )
            if members:
                for muid in members:
                    self.user_locations[muid] = {"session_id": session_id, "group_id": group_id}
                    self.record_participant_group(session_id, muid, group_id)
            print(f"🏠 Group {group_id} under {session_id} (Members: {members}, condition: {condition})")
        return group_id

    def resolve_session_id_for_group(self, group_id: str) -> Optional[str]:
        """Map group_id → session_id for active, queued, or ended groups (usage rollups)."""
        if not group_id:
            return None
        for sid, groups in self.active_rooms.items():
            if group_id in groups:
                return sid
        for sid, by_uid in self.participant_groups.items():
            for gid in by_uid.values():
                if gid == group_id:
                    return sid
        try:
            from usage_tracker import get_group_usage

            sid = get_group_usage(group_id).get("session_id")
            if sid and sid != "_unknown":
                return sid
        except Exception:
            pass
        return None

    def get_group_info(self, session_id: str, group_id: str) -> Optional[Dict]:
        if session_id in self.active_rooms and group_id in self.active_rooms[session_id]:
            return self.active_rooms[session_id][group_id]
        return None

    def end_group(self, session_id: str, group_id: str):
        if session_id in self.active_rooms and group_id in self.active_rooms[session_id]:
            group_info = self.active_rooms[session_id][group_id]
            for muid in group_info.get("members", []):
                if muid in self.user_locations:
                    del self.user_locations[muid]
            del self.active_rooms[session_id][group_id]
            print(f"🔚 Group {group_id} in Session {session_id} closed.")


match_manager = MatchManager()
