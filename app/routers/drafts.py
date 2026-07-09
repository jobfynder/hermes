from fastapi import APIRouter, HTTPException

from app.drafts.models import DraftObject, DraftPublishResult
from app.drafts.service import (
    get_draft_object,
    list_draft_objects,
    publish_draft_object,
)

router = APIRouter(prefix="/drafts", tags=["Drafts"])


@router.get("", response_model=list[DraftObject])
def list_drafts() -> list[DraftObject]:
    return list_draft_objects()


@router.get("/{draft_id}", response_model=DraftObject)
def read_draft(draft_id: str) -> DraftObject:
    draft = get_draft_object(draft_id)

    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    return draft


@router.post("/{draft_id}/publish", response_model=DraftPublishResult)
def publish_draft(draft_id: str) -> DraftPublishResult:
    return publish_draft_object(draft_id)
