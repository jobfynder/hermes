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


class ResumeSummarySuggestionRequest(BaseModel):
    source_text: str = Field(..., min_length=1)
    target_role: str | None = None
    tone: str | None = None
    constraints: str | None = None
    source_references: list[ResumeSourceReference] = Field(
        default_factory=list
    )
    correlation_id: str | None = None
    actor_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeBulletSuggestionRequest(BaseModel):
    source_text: str = Field(..., min_length=1)
    target_role: str | None = None
    skills_to_emphasize: list[str] = Field(default_factory=list)
    constraints: str | None = None
    source_references: list[ResumeSourceReference] = Field(
        default_factory=list
    )
    correlation_id: str | None = None
    actor_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeSuggestionResponse(BaseModel):
    result_version: str = "hermes_resume_suggestion_v1"
    suggestion_type: Literal["summary", "bullet"]
    decision: ResumeBuilderDecision
    prompt_id: str
    prompt_version: str
    mode_requested: Literal["dry_run"] = "dry_run"
    mode_effective: Literal["dry_run"] = "dry_run"
    provider: str
    output_text: str | None = None
    human_review_required: bool = True
    source_traceability_present: bool
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    rendered_messages: list[dict[str, str]] = Field(
        default_factory=list
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeSkillNormalizationRequest(BaseModel):
    skills: list[str] = Field(default_factory=list)
    source_references: list[ResumeSourceReference] = Field(
        default_factory=list
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeNormalizedSkill(BaseModel):
    input: str
    normalized: str
    matched: bool
    match_type: Literal["canonical", "alias", "unknown"]
    confidence: Literal["high", "medium", "low"]
    taxonomy_version: str


class ResumeSkillNormalizationResponse(BaseModel):
    result_version: str = "hermes_resume_skill_normalization_v1"
    decision: ResumeBuilderDecision
    normalized_skills: list[ResumeNormalizedSkill] = Field(
        default_factory=list
    )
    canonical_skills: list[str] = Field(default_factory=list)
    unknown_skills: list[str] = Field(default_factory=list)
    human_review_required: bool = True
    external_ai_used: bool = False
    source_traceability_present: bool = False
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeTailoringRequest(BaseModel):
    resume: dict[str, Any] = Field(default_factory=dict)
    job: dict[str, Any] = Field(default_factory=dict)
    source_references: list[ResumeSourceReference] = Field(
        default_factory=list
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeTailoringOpportunity(BaseModel):
    code: str
    category: Literal[
        "matched_skill",
        "missing_required_skill",
        "preferred_skill",
        "experience",
        "location",
        "work_authorization",
        "general",
    ]
    message: str
    skill: str | None = None
    requires_user_input: bool = False
    safe_to_emphasize: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeTailoringResponse(BaseModel):
    result_version: str = "hermes_resume_tailoring_v1"
    decision: ResumeBuilderDecision
    match_decision: str
    match_score: float
    matched_required_skills: list[str] = Field(default_factory=list)
    missing_required_skills: list[str] = Field(default_factory=list)
    matched_preferred_skills: list[str] = Field(default_factory=list)
    opportunities: list[ResumeTailoringOpportunity] = Field(
        default_factory=list
    )
    human_review_required: bool = True
    automatic_rewrite_allowed: bool = False
    external_ai_used: bool = False
    source_traceability_present: bool = False
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
