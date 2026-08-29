from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.claim.models import EmailClaim
from app.claim.service import get_claim_by_draft
from app.drafts.models import DraftObject, DraftObjectType, DraftPublishResult
from app.drafts.service import (
    get_draft_object,
    list_draft_objects,
    publish_draft_object,
    reclassify_draft_object,
    reject_draft_object,
)
from app.email_parsing.provenance import load_field_provenance
from app.security.rbac import require_permission


class RejectDraftRequest(BaseModel):
    reason: str | None = None


class ReclassifyDraftRequest(BaseModel):
    corrected_draft_type: DraftObjectType


class FieldProvenanceEntry(BaseModel):
    field_path: str
    raw_value: Any = None
    normalized_value: Any = None
    source_region: str | None = None
    extractor: str
    extraction_method: str
    confidence: float
    value_kind: str
    recorded_at: str


router = APIRouter(prefix="/drafts", tags=["Drafts"])


@router.get("", response_model=list[DraftObject])
def list_drafts(
    _user: dict = Depends(require_permission("drafts:read")),
) -> list[DraftObject]:
    return list_draft_objects()


@router.get("/{draft_id}", response_model=DraftObject)
def read_draft(
    draft_id: str,
    _user: dict = Depends(require_permission("drafts:read")),
) -> DraftObject:
    draft = get_draft_object(draft_id)

    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    return draft


@router.get("/{draft_id}/provenance", response_model=list[FieldProvenanceEntry])
def read_draft_provenance(
    draft_id: str,
    _user: dict = Depends(require_permission("drafts:read")),
) -> list[dict]:
    """Every field Hermes extracted for this draft, with where it came
    from (deterministic parser, LLM fallback, or a recruiter's own
    correction) and how confident that pass was -- this is the actual
    verification surface a reviewer needs, not just the final values.
    """
    draft = get_draft_object(draft_id)

    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    return load_field_provenance(draft_id)


@router.get("/{draft_id}/claim", response_model=EmailClaim)
def read_draft_claim(
    draft_id: str,
    _user: dict = Depends(require_permission("drafts:read")),
) -> EmailClaim:
    claim = get_claim_by_draft(draft_id)

    if not claim:
        raise HTTPException(status_code=404, detail="No claim exists for this draft")

    return claim


@router.post("/{draft_id}/publish", response_model=DraftPublishResult)
def publish_draft(
    draft_id: str,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> DraftPublishResult:
    return publish_draft_object(draft_id)


@router.post("/{draft_id}/reject", response_model=DraftPublishResult)
def reject_draft(
    draft_id: str,
    body: RejectDraftRequest,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> DraftPublishResult:
    return reject_draft_object(draft_id, body.reason)


@router.post("/{draft_id}/reclassify", response_model=DraftObject)
def reclassify_draft(
    draft_id: str,
    body: ReclassifyDraftRequest,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> DraftObject:
    """A reviewer correcting what kind of record this draft actually is
    (e.g. it was parsed as a job requirement but is really a hotlist).
    When the correction is between hotlist and job requirement -- the
    only two kinds Hermes's own content classifier distinguishes between
    -- this also teaches app/email_parsing/classification_learning.py,
    so future ambiguous emails from the same sender lean the way this
    one was actually corrected.
    """
    draft = reclassify_draft_object(draft_id, body.corrected_draft_type)

    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    return draft
