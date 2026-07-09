from typing import Literal

from pydantic import BaseModel, Field


UserRole = Literal[
    "bench_sales_recruiter",
    "recruiter",
    "consultant",
    "admin",
    "unknown",
]

ActionName = Literal[
    "post_hotlist",
    "add_candidate",
    "upload_resume",
    "update_candidate_availability",
    "post_job_requirement",
    "upload_jd",
    "request_candidates",
    "review_submission",
    "onboarding_start",
    "onboarding_create_draft",
]

AccessDecisionStatus = Literal["allowed", "denied"]


class ActionAccessRequest(BaseModel):
    actor_id: str
    role: UserRole
    action: ActionName
    channel: str = "generic_api"
    metadata: dict = Field(default_factory=dict)


class ActionAccessDecision(BaseModel):
    status: AccessDecisionStatus
    actor_id: str
    role: UserRole
    action: ActionName
    channel: str
    reason: str | None = None
    allowed_actions: list[str] = Field(default_factory=list)
