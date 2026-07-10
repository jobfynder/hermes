from typing import Any, Literal

from pydantic import BaseModel, Field


ResumeBuilderDecision = Literal[
    "completed",
    "needs_review",
    "blocked",
    "failed",
]

ResumeSectionKind = Literal[
    "contact",
    "summary",
    "skills",
    "experience",
    "education",
    "certifications",
    "projects",
    "other",
]


class ResumeSourceReference(BaseModel):
    source_id: str
    source_type: Literal[
        "resume_text",
        "parsed_resume",
        "verified_profile",
        "user_input",
    ]
    field_path: str | None = None
    excerpt: str | None = None
    verified: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeBuilderSafetyPolicy(BaseModel):
    policy_version: str = "hermes_resume_builder_safety_v1"
    fabrication_allowed: bool = False
    human_review_required: bool = True
    automatic_publish_allowed: bool = False
    external_ai_enabled: bool = False
    prompt_runtime_mode: Literal["dry_run"] = "dry_run"
    source_traceability_required: bool = True


class ResumeBuilderHealthResponse(BaseModel):
    status: str = "healthy"
    module: str = "HERMES-800"
    service: str = "resume_builder_intelligence"
    foundation_version: str = "hermes_resume_builder_v1"
    deterministic_analysis_enabled: bool = True
    prompt_runtime_available: bool = True
    prompt_runtime_default_mode: Literal["dry_run"] = "dry_run"
    external_ai_enabled: bool = False
    human_review_required: bool = True
    automatic_publish_allowed: bool = False


class ResumeSectionInput(BaseModel):
    section_id: str
    section_type: ResumeSectionKind
    title: str | None = None
    content: str = ""
    source_references: list[ResumeSourceReference] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeDocumentInput(BaseModel):
    resume_id: str | None = None
    user_id: str | None = None
    target_job_id: str | None = None
    source_text: str | None = None
    sections: list[ResumeSectionInput] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeIssue(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    section_id: str | None = None
    field_path: str | None = None
    requires_user_input: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeBuilderResult(BaseModel):
    result_version: str = "hermes_resume_builder_result_v1"
    decision: ResumeBuilderDecision
    human_review_required: bool = True
    issues: list[ResumeIssue] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
