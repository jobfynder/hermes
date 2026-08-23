from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.drafts.models import DraftObject, DraftPublishResult
from app.drafts.service import (
    get_draft_object,
    list_draft_objects,
    publish_draft_object,
    reject_draft_object,
)
from app.security.rbac import require_permission


class RejectDraftRequest(BaseModel):
    reason: str | None = None

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
