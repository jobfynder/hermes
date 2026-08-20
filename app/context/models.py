from typing import Any

from pydantic import BaseModel, Field


class CandidateCardV1(BaseModel):
    card_version: str = "hermes_candidate_card_v1"
    title: str | None = None
    years_experience: int | None = None
    skills: list[str] = Field(default_factory=list)
    location: str | None = None
    work_authorization: str | None = None
    availability: str | None = None
    rate: str | None = None
    summary_snippet: str | None = None
    source_confidence: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobCardV1(BaseModel):
    card_version: str = "hermes_job_card_v1"
    title: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    years_experience: int | None = None
    location: str | None = None
    employment_type: str | None = None
    work_authorization: str | None = None
    rate_or_salary: str | None = None
    summary_snippet: str | None = None
    source_confidence: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RelationshipCardV1(BaseModel):
    card_version: str = "hermes_relationship_card_v1"
    contact_name: str | None = None
    relationship_type: str | None = None
    shared_context: list[str] = Field(default_factory=list)
    last_interaction_summary: str | None = None
    interaction_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationContextV1(BaseModel):
    context_version: str = "hermes_conversation_context_v1"
    compressed_text: str
    message_count: int
    original_token_count: int
    compressed_token_count: int
    compression_applied: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateCardBuildRequest(BaseModel):
    source_text: str | None = None
    structured_resume: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobCardBuildRequest(BaseModel):
    source_text: str | None = None
    structured_job: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RelationshipCardBuildRequest(BaseModel):
    contact_name: str | None = None
    relationship_type: str | None = None
    interactions: list[dict[str, Any]] = Field(default_factory=list)
    shared_context: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationCompressRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)
    max_tokens: int = 800
    metadata: dict[str, Any] = Field(default_factory=dict)
