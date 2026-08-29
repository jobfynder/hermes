from typing import Any, Literal

from pydantic import BaseModel, Field


DraftObjectType = Literal[
    "draft_consultant_profile",
    "draft_job_requirement",
    "draft_recruiter_profile",
    "draft_bench_sales_profile",
    "draft_hotlist",
    "draft_vendor_list",
    "draft_channel_note",
]

DraftStatus = Literal[
    "draft",
    "needs_review",
    "published",
    "rejected",
    # Heuristically flagged as likely spam/junk (app/email_parsing/spam.py)
    # -- distinct from a blocked sender, which never becomes a draft at
    # all. Flag-only by design: nothing here is ever auto-deleted, a human
    # reviews it in the frontend and either deletes it or reclassifies it
    # back to draft if the heuristic was wrong.
    "spam",
]


class DraftObject(BaseModel):
    draft_id: str
    draft_type: DraftObjectType
    status: DraftStatus = "draft"
    source: str
    source_ref: str | None = None
    channel: str | None = None
    source_message_id: str | None = None
    title: str | None = None
    summary: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    normalized_skills: list[str] = Field(default_factory=list)
    normalized_job_titles: list[str] = Field(default_factory=list)
    taxonomy_signals: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    requires_review: bool = True
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class DraftPublishResult(BaseModel):
    status: str
    draft_id: str
    draft_type: DraftObjectType
    published_payload: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
