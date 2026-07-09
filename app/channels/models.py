from typing import Any, Literal

from pydantic import BaseModel, Field


ChannelName = Literal[
    "generic_api",
    "telegram",
    "email",
    "whatsapp",
    "slack",
    "teams",
    "google_chat",
    "browser_extension",
    "web_upload",
]

ContentType = Literal["text", "file", "mixed", "unknown"]

IntakeStatus = Literal[
    "received",
    "validated",
    "stored",
    "parsing",
    "parsed",
    "normalized",
    "draft_created",
    "needs_review",
    "failed",
    "duplicate",
]

DocumentKind = Literal[
    "resume",
    "job_description",
    "hotlist",
    "recruiter_profile",
    "bench_sales_profile",
    "consultant_profile",
    "vendor_list",
    "plain_message",
    "unknown",
]


class ChannelAttachment(BaseModel):
    file_id: str | None = None
    filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    source_url: str | None = None
    storage_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChannelSender(BaseModel):
    sender_id: str | None = None
    sender_name: str | None = None
    username: str | None = None
    email: str | None = None
    phone: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChannelIntakeRequest(BaseModel):
    channel: ChannelName
    source_message_id: str
    actor_id: str | None = None
    role: str | None = None
    action: str | None = None
    sender: ChannelSender = Field(default_factory=ChannelSender)
    workspace_id: str | None = None
    conversation_id: str | None = None
    content_type: ContentType = "unknown"
    text: str | None = None
    attachments: list[ChannelAttachment] = Field(default_factory=list)
    received_at: str | None = None
    raw_payload_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChannelIntakeResponse(BaseModel):
    channel: ChannelName
    source_message_id: str
    intake_status: IntakeStatus
    document_kind: DocumentKind
    understanding_result: dict[str, Any] = Field(default_factory=dict)
    taxonomy_signals: dict[str, Any] = Field(default_factory=dict)
    normalized_skills: list[str] = Field(default_factory=list)
    normalized_job_titles: list[str] = Field(default_factory=list)
    draft_object_type: str | None = None
    requires_review: bool = False
    confidence: float = 0.0
    errors: list[str] = Field(default_factory=list)
    duplicate_key: str
