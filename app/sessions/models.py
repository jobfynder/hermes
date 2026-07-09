from typing import Literal

from pydantic import BaseModel, Field


ConversationState = Literal[
    "new",
    "menu_shown",
    "waiting_for_hotlist",
    "waiting_for_candidate",
    "waiting_for_job_requirement",
    "waiting_for_onboarding",
    "completed",
    "blocked",
]


class ConversationSession(BaseModel):
    session_id: str
    channel: str
    external_user_id: str
    chat_id: str | None = None
    role: str | None = None
    action: str | None = None
    state: ConversationState = "new"
    expected_input: str | None = None
    metadata: dict = Field(default_factory=dict)


class ConversationTransition(BaseModel):
    session: ConversationSession
    should_parse: bool = False
    response_text: str | None = None
    reason: str | None = None
