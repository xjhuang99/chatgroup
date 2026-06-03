"""Pydantic request bodies for HTTP APIs."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from env_defaults import default_group_spend_cap_usd


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AccountRegisterRequest(BaseModel):
    email: str
    username: Optional[str] = None
    password: Optional[str] = None


class AccountProfileUpdateRequest(BaseModel):
    current_password: str
    username: Optional[str] = None
    new_password: Optional[str] = None


class AdminAccountCapUpdate(BaseModel):
    spend_cap_usd: float


class SessionCreateRequest(BaseModel):
    session_name: str
    group_size: int
    min_humans_per_group: Optional[int] = Field(default=None, ge=1, le=20)
    max_humans_per_group: Optional[int] = Field(default=None, ge=1, le=20)
    bot_enabled: bool
    bots: List[Dict]
    participant_names: Optional[List[str]] = None
    session_mode: int = Field(default=1, ge=1, le=4)
    survey_open_days: int = 7
    group_chat_duration_minutes: int = 3
    qualtrics_handoff_enabled: bool = True
    qualtrics_store_chat: bool = True
    qualtrics_field_transcript: str = "transcript"
    qualtrics_field_status: str = "chat_status"
    ai_starts_conversation: bool = True
    turn_mode: str = "none"
    turn_duration_seconds: int = 60
    assignment_mode: str = "fifo"
    condition_enabled: bool = True
    style_mimic_enabled: bool = False
    style_mimic_target: str = "c"
    bot_reply_on_any_message: bool = True
    max_chain_depth: int = 2
    use_mentions: bool = False
    mention_prob: float = 0.0
    self_correction_prob: float = 0.0
    group_spend_cap_usd: float = Field(default_factory=default_group_spend_cap_usd)
    parallel_start_jitter_sec: float = 1.5
    rethink_seconds: float = 2.0
    max_refresh_attempts: int = 2
    qualtrics_log_mode: str = "transcript"


class SessionUpdateRequest(BaseModel):
    session_name: Optional[str] = None
    group_size: Optional[int] = None
    min_humans_per_group: Optional[int] = Field(default=None, ge=1, le=20)
    max_humans_per_group: Optional[int] = Field(default=None, ge=1, le=20)
    bot_enabled: Optional[bool] = None
    bots: Optional[List[Dict]] = None
    participant_names: Optional[List[str]] = None
    history_limit: Optional[int] = None
    session_mode: Optional[int] = Field(default=None, ge=1, le=4)
    survey_open_days: Optional[int] = None
    group_chat_duration_minutes: Optional[int] = None
    qualtrics_handoff_enabled: Optional[bool] = None
    qualtrics_store_chat: Optional[bool] = None
    qualtrics_field_transcript: Optional[str] = None
    qualtrics_field_status: Optional[str] = None
    ai_starts_conversation: Optional[bool] = None
    turn_mode: Optional[str] = None
    turn_duration_seconds: Optional[int] = None
    assignment_mode: Optional[str] = None
    condition_enabled: Optional[bool] = None
    style_mimic_enabled: Optional[bool] = None
    style_mimic_target: Optional[str] = None
    bot_reply_on_any_message: Optional[bool] = None
    max_chain_depth: Optional[int] = None
    use_mentions: Optional[bool] = None
    mention_prob: Optional[float] = None
    self_correction_prob: Optional[float] = None
    group_spend_cap_usd: Optional[float] = None
    parallel_start_jitter_sec: Optional[float] = None
    rethink_seconds: Optional[float] = None
    max_refresh_attempts: Optional[int] = None
    qualtrics_log_mode: Optional[str] = None


class EmbedHandoffRequest(BaseModel):
    session_id: str
    participant_id: str
    reason: str = "page_unload"
