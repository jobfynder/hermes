from typing import Literal

from pydantic import BaseModel, Field


OnboardingRole = Literal["bench_sales", "recruiter", "consultant", "unknown"]
OnboardingChannel = Literal[
    "web",
    "telegram",
    "whatsapp",
    "email",
    "slack",
    "teams",
    "google_chat",
    "generic_api",
]
OnboardingStatus = Literal[
    "started",
    "role_selected",
    "profile_text_received",
    "draft_created",
    "needs_review",
    "published",
    "failed",
]


class OnboardingSessionRequest(BaseModel):
    user_id: str | None = None
    role: OnboardingRole = "unknown"
    channel: OnboardingChannel = "web"
    channel_user_id: str | None = None
    sender_name: str | None = None
    metadata: dict = Field(default_factory=dict)


class OnboardingSession(BaseModel):
    session_id: str
    user_id: str | None = None
    role: OnboardingRole
    channel: OnboardingChannel
    channel_user_id: str | None = None
    sender_name: str | None = None
    status: OnboardingStatus
    metadata: dict = Field(default_factory=dict)


class OnboardingProfileDraftRequest(BaseModel):
    session_id: str
    role: OnboardingRole
    profile_text: str
    source: str = "manual_text"
    metadata: dict = Field(default_factory=dict)


class OnboardingProfileDraft(BaseModel):
    result_version: str = "hermes_onboarding_profile_draft_v1"
    session_id: str
    role: OnboardingRole
    profile_status: Literal["draft"] = "draft"
    display_name: str | None = None
    headline: str | None = None
    company: str | None = None
    location: str | None = None
    summary: str | None = None
    specializations: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    trust_signals: dict = Field(default_factory=dict)
    visibility: str = "private_until_published"
    created_from: str
    requires_review: bool = True
    confidence: float = 0.0
    understanding_result: dict = Field(default_factory=dict)
    taxonomy_signals: dict = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    llm_fallback: dict = Field(default_factory=dict)


class OnboardingVerificationDraftRequest(BaseModel):
    session_id: str
    role: OnboardingRole
    full_name: str
    company_name: str | None = None
    company_email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    location: str | None = None
    staffing_focus: str | None = None
    notes: str | None = None
    channel: str = "generic_api"
    metadata: dict = Field(default_factory=dict)


class OnboardingVerificationDraft(BaseModel):
    result_version: str = "hermes_onboarding_verification_draft_v1"
    session_id: str
    role: OnboardingRole
    status: Literal["draft", "needs_review", "blocked"] = "needs_review"
    full_name: str
    company_name: str | None = None
    company_email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    location: str | None = None
    staffing_focus: str | None = None
    trust_signals: dict = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    requires_admin_review: bool = True
    confidence: float = 0.0
    errors: list[str] = Field(default_factory=list)
