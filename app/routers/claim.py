from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.claim.models import ClaimConfirmResult, ClaimPrepareResult, EmailClaim
from app.claim.service import confirm_claim, get_claim_by_token, mark_claim_sent, prepare_claim
from app.security.rbac import require_permission


class PrepareClaimRequest(BaseModel):
    draft_id: str


class ConfirmClaimRequest(BaseModel):
    corrections: dict[str, Any] = Field(default_factory=dict)


router = APIRouter(prefix="/claim", tags=["Email Claim & Verify"])


@router.post("/prepare", response_model=ClaimPrepareResult)
def prepare(
    body: PrepareClaimRequest,
    _user: dict = Depends(require_permission("claim:prepare")),
) -> ClaimPrepareResult:
    """Internal call (Core/n8n) once a parsed email job-requirement draft
    reaches READY. Returns the claim link and deterministic email content
    for the caller to actually send -- Hermes never dispatches mail itself.
    """
    return prepare_claim(body.draft_id)


@router.post("/{claim_id}/mark-sent", response_model=EmailClaim)
def mark_sent(
    claim_id: str,
    _user: dict = Depends(require_permission("claim:prepare")),
) -> EmailClaim:
    """Internal call (Core/n8n) confirming the claim email was actually
    delivered, for claim_emails_sent / avg_time_to_claim metrics."""
    claim = mark_claim_sent(claim_id)

    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    return claim


@router.get("/{token}", response_model=EmailClaim)
def read_claim(token: str) -> EmailClaim:
    """Public: the recruiter's browser fetches the prefilled listing via
    the link in the claim email. No bearer token -- the claim token itself
    is the credential (spec 11.1: \"recruiter clicks through\")."""
    claim = get_claim_by_token(token)

    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    return claim


@router.post("/{token}/confirm", response_model=ClaimConfirmResult)
def confirm(token: str, body: ConfirmClaimRequest) -> ClaimConfirmResult:
    """Public: the recruiter submits corrections (if any) and publishes.
    Each corrected field becomes a recruiter_correction provenance row --
    this is the accuracy ground truth the claim loop exists to produce."""
    result = confirm_claim(token, body.corrections)

    if result.status == "blocked" and "claim_not_found" in result.errors:
        raise HTTPException(status_code=404, detail="Claim not found")

    if result.status == "blocked" and "claim_expired" in result.errors:
        raise HTTPException(status_code=410, detail="Claim link has expired")

    return result
