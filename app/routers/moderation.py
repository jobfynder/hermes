from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException

from app.email_parsing.blocklist import add_block, list_blocks, remove_block
from app.security.rbac import require_permission
from app.understanding.taxonomy.candidates import (
    approve_taxonomy_candidate,
    list_taxonomy_candidates,
    reject_taxonomy_candidate,
)


class BlocklistEntry(BaseModel):
    id: int
    match_type: str
    value: str
    reason: str | None = None
    source_draft_id: str | None = None
    created_at: str


class AddBlockRequest(BaseModel):
    match_type: str
    value: str
    reason: str | None = None


class RemoveBlockResult(BaseModel):
    removed: bool


class TaxonomyCandidateEntry(BaseModel):
    id: int
    signal_type: str
    term: str
    normalized_term: str
    occurrence_count: int
    distinct_senders: list[str]
    sample_draft_ids: list[str]
    status: str
    first_seen_at: str
    last_seen_at: str


class ApproveCandidateRequest(BaseModel):
    category: str = "Tool/Technology"
    skill_type: str = "tool"


class CandidateActionResult(BaseModel):
    ok: bool
    term: str | None = None
    reason: str | None = None


router = APIRouter(tags=["Moderation"])


@router.get("/blocklist", response_model=list[BlocklistEntry])
def get_blocklist(
    _user: dict = Depends(require_permission("drafts:read")),
) -> list[dict]:
    return list_blocks()


@router.post("/blocklist", response_model=BlocklistEntry)
def create_block(
    body: AddBlockRequest,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> dict:
    if body.match_type not in {"domain", "email"}:
        raise HTTPException(status_code=400, detail="match_type must be 'domain' or 'email'")

    return add_block(match_type=body.match_type, value=body.value, reason=body.reason)


@router.delete("/blocklist/{block_id}", response_model=RemoveBlockResult)
def delete_block(
    block_id: int,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> RemoveBlockResult:
    return RemoveBlockResult(removed=remove_block(block_id))


@router.get("/taxonomy-candidates", response_model=list[TaxonomyCandidateEntry])
def get_taxonomy_candidates(
    status: str = "pending",
    _user: dict = Depends(require_permission("drafts:read")),
) -> list[dict]:
    return list_taxonomy_candidates(status=status)


@router.post("/taxonomy-candidates/{candidate_id}/approve", response_model=CandidateActionResult)
def approve_candidate(
    candidate_id: int,
    body: ApproveCandidateRequest,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> CandidateActionResult:
    result = approve_taxonomy_candidate(
        candidate_id, category=body.category, skill_type=body.skill_type
    )
    return CandidateActionResult(ok=result.get("approved", False), term=result.get("term"), reason=result.get("reason"))


@router.post("/taxonomy-candidates/{candidate_id}/reject", response_model=CandidateActionResult)
def reject_candidate(
    candidate_id: int,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> CandidateActionResult:
    result = reject_taxonomy_candidate(candidate_id)
    return CandidateActionResult(ok=result.get("rejected", False), term=result.get("term"), reason=result.get("reason"))
