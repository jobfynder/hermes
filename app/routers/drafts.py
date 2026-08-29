from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.drafts.models import DraftObject, DraftObjectType, DraftPublishResult
from app.drafts.service import (
    get_draft_object,
    list_draft_objects,
    publish_draft_object,
    reclassify_draft_object,
    reject_draft_object,
)
from app.security.rbac import require_permission


class RejectDraftRequest(BaseModel):
    reason: str | None = None


class ReclassifyDraftRequest(BaseModel):
    corrected_draft_type: DraftObjectType


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
