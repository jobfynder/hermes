from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.claim.models import EmailClaim
from app.claim.service import get_claim_by_draft
from app.drafts.models import DraftObject, DraftObjectType, DraftPublishResult
from app.drafts.service import (
    delete_draft_object,
    get_draft_object,
    list_draft_objects,
    publish_draft_object,
    reclassify_draft_object,
    reject_draft_object,
)
from app.email_parsing.blocklist import add_block, extract_domain
from app.email_parsing.provenance import load_field_provenance
from app.security.rbac import require_permission


class RejectDraftRequest(BaseModel):
    reason: str | None = None


class ReclassifyDraftRequest(BaseModel):
    corrected_draft_type: DraftObjectType


class DeleteDraftResult(BaseModel):
    deleted: bool
    reason: str | None = None


class BlockSenderRequest(BaseModel):
    # "domain" blocks every address at the sender's domain; "email" blocks
    # only the exact address this draft came from. Defaults to "domain" --
    # a single junk sender at a domain is usually not a one-off.
    match_type: str = "domain"
    reason: str | None = None


class BlockSenderResult(BaseModel):
    blocked: bool
    match_type: str | None = None
    value: str | None = None
    reason: str | None = None


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


@router.delete("/{draft_id}", response_model=DeleteDraftResult)
def delete_draft(
    draft_id: str,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> DeleteDraftResult:
    """Permanently removes a draft -- the one destructive endpoint on this
    router. Meant for the spam-review workflow: a human confirmed a
    status='spam' draft really is junk and wants it gone, not just
    rejected-and-kept. See delete_draft_object's docstring for why a
    published draft, or one with a claim/Core push already attached to
    it, refuses instead of deleting.
    """
    result = delete_draft_object(draft_id)
    return DeleteDraftResult(**result)


@router.post("/{draft_id}/block-sender", response_model=BlockSenderResult)
def block_draft_sender(
    draft_id: str,
    body: BlockSenderRequest,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> BlockSenderResult:
    """Adds this draft's own sender (or its domain) to the blocklist, so
    every future message from them is discarded before it ever becomes a
    draft -- see app/email_parsing/blocklist.py and the block check at the
    top of process_channel_intake. Does not touch this draft itself or
    any other draft already in the queue; pair with DELETE if this
    particular one should also go away.
    """
    draft = get_draft_object(draft_id)

    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    sender_email = ((draft.metadata or {}).get("sender") or {}).get("email")

    if not sender_email:
        return BlockSenderResult(blocked=False, reason="draft_has_no_sender_email")

    if body.match_type == "email":
        value = sender_email
    else:
        domain = extract_domain(sender_email)
        if not domain:
            return BlockSenderResult(blocked=False, reason="sender_email_has_no_domain")
        value = domain

    row = add_block(
        match_type=body.match_type,
        value=value,
        reason=body.reason,
        source_draft_id=draft_id,
    )

    return BlockSenderResult(blocked=True, match_type=row["match_type"], value=row["value"])
