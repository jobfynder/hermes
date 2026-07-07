from typing import Any, Literal

from pydantic import BaseModel, Field


SubmissionStage = Literal[
    "discovered",
    "matched",
    "intro_requested",
    "intro_accepted",
    "submitted",
    "screening",
    "client_submitted",
    "interview",
    "offer",
    "placed",
    "rejected",
    "withdrawn",
    "duplicate_risk",
    "closed_lost",
]

SubmissionActorRole = Literal[
    "consultant",
    "bench_sales_recruiter",
    "recruiter",
    "employer",
    "vendor",
    "system",
    "unknown",
]

SubmissionEventType = Literal[
    "submission_created",
    "match_detected",
    "intro_requested",
    "intro_accepted",
    "intro_declined",
    "submitted",
    "stage_changed",
    "follow_up_required",
    "follow_up_completed",
    "duplicate_risk_detected",
    "outcome_recorded",
    "note_added",
]

FollowUpPriority = Literal["low", "medium", "high"]

OutcomeType = Literal[
    "none",
    "submitted",
    "screening",
    "client_submitted",
    "interview",
    "offer",
    "placed",
    "rejected",
    "withdrawn",
    "closed_lost",
]


class SubmissionParty(BaseModel):
    party_id: str | None = None
    name: str | None = None
    role: SubmissionActorRole = "unknown"
    email: str | None = None
    company: str | None = None


class SubmissionRequirementSnapshot(BaseModel):
    job_id: str | None = None
    title: str | None = None
    client: str | None = None
    location: str | None = None
    work_authorization: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    raw_source: str | None = None


class SubmissionConsultantSnapshot(BaseModel):
    consultant_id: str | None = None
    name: str | None = None
    location: str | None = None
    work_authorization: str | None = None
    skills: list[str] = Field(default_factory=list)
    years_experience: float | None = None
    resume_id: str | None = None


class SubmissionRelationshipSnapshot(BaseModel):
    recruiter: SubmissionParty | None = None
    bench_sales_recruiter: SubmissionParty | None = None
    employer: SubmissionParty | None = None
    vendor: SubmissionParty | None = None
    relationship_strength: str | None = None
    trust_level: str | None = None


class SubmissionEvent(BaseModel):
    event_type: SubmissionEventType
    from_stage: SubmissionStage | None = None
    to_stage: SubmissionStage | None = None
    actor: SubmissionParty = Field(default_factory=SubmissionParty)
    note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FollowUp(BaseModel):
    required: bool = False
    reason: str | None = None
    priority: FollowUpPriority = "medium"
    suggested_action: str | None = None


class SubmissionConflict(BaseModel):
    conflict_type: str
    severity: Literal["low", "medium", "high"] = "medium"
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Outcome(BaseModel):
    outcome_type: OutcomeType = "none"
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubmissionIntelligenceRequest(BaseModel):
    submission_id: str | None = None
    current_stage: SubmissionStage = "discovered"
    event: SubmissionEvent | None = None
    requirement: SubmissionRequirementSnapshot = Field(default_factory=SubmissionRequirementSnapshot)
    consultant: SubmissionConsultantSnapshot = Field(default_factory=SubmissionConsultantSnapshot)
    relationship: SubmissionRelationshipSnapshot = Field(default_factory=SubmissionRelationshipSnapshot)
    match_result: dict[str, Any] = Field(default_factory=dict)
    parser_result: dict[str, Any] = Field(default_factory=dict)
    taxonomy_context: dict[str, Any] = Field(default_factory=dict)
    existing_submission_keys: list[str] = Field(default_factory=list)


class SubmissionIntelligenceResult(BaseModel):
    result_version: str = "hermes_submission_intelligence_result_v1"
    workflow_version: str = "hermes_submission_workflow_v1"
    submission_id: str | None = None
    current_stage: SubmissionStage
    recommended_stage: SubmissionStage
    stage_changed: bool = False
    events: list[SubmissionEvent] = Field(default_factory=list)
    follow_up: FollowUp = Field(default_factory=FollowUp)
    conflicts: list[SubmissionConflict] = Field(default_factory=list)
    outcome: Outcome = Field(default_factory=Outcome)
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    handoff: dict[str, Any] = Field(default_factory=dict)


class SubmissionWorkflowPolicyResponse(BaseModel):
    workflow_version: str
    supported_stages: list[str]
    allowed_transitions: dict[str, list[str]]
    terminal_stages: list[str]
