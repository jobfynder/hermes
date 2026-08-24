from typing import Any, Literal

from pydantic import BaseModel, Field


ClaimStatus = Literal[
    'PENDING_CLAIM',
    'CLAIMED',
    'PUBLISHED',
    'EXPIRED',
]

ClaimResolutionMethod = Literal[
    'forwarded_header',
    'reply_to_header',
    'body_contact',
    'direct_sender',
]


class EmailClaim(BaseModel):
    claim_id: str
    draft_id: str
    token: str
    status: ClaimStatus = 'PENDING_CLAIM'
    recruiter_email: str
    recruiter_name: str | None = None
    resolution_method: ClaimResolutionMethod
    resolution_confidence: float = Field(ge=0.0, le=1.0)
    prefilled_fields: dict[str, Any] = Field(default_factory=dict)
    correction_diff: dict[str, Any] | None = None
    created_at: str
    sent_at: str | None = None
    claimed_at: str | None = None
    published_at: str | None = None
    expires_at: str


class ClaimPrepareResult(BaseModel):
    status: Literal['prepared', 'already_prepared', 'blocked']
    claim: EmailClaim | None = None
    email_subject: str | None = None
    email_body: str | None = None
    claim_url_path: str | None = None
    errors: list[str] = Field(default_factory=list)


class ClaimConfirmResult(BaseModel):
    status: Literal['claimed', 'blocked']
    claim: EmailClaim | None = None
    correction_diff: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
