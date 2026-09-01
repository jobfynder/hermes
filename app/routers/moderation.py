from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException

from app.email_parsing.blocklist import add_block, list_blocks, remove_block
from app.security.rbac import require_permission
from app.understanding.taxonomy.candidates import (
    approve_taxonomy_candidate,
    bulk_approve_taxonomy_candidates,
    bulk_reject_taxonomy_candidates,
    edit_taxonomy_candidate,
    list_taxonomy_candidates,
    reject_taxonomy_candidate,
    update_skill_description,
)
from app.understanding.taxonomy.loader import bulk_set_job_title_family, update_canonical_job_title


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
    # Used when approving a signal_type='skill' candidate.
    category: str = "Tool/Technology"
    skill_type: str = "tool"
    # Used when approving a signal_type='job_title' candidate.
    family: str = "Unclassified"
    seniority: str = "unspecified"


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


class EditCandidateRequest(BaseModel):
    term: str


@router.patch("/taxonomy-candidates/{candidate_id}", response_model=CandidateActionResult)
def edit_candidate(
    candidate_id: int,
    body: EditCandidateRequest,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> CandidateActionResult:
    """Corrects a parser artifact in a pending candidate's term (e.g. a
    stray "AWS (required)") before it's approved into the taxonomy.
    """
    result = edit_taxonomy_candidate(candidate_id, body.term)
    return CandidateActionResult(ok=result.get("edited", False), term=result.get("term"), reason=result.get("reason"))


@router.post("/taxonomy-candidates/{candidate_id}/approve", response_model=CandidateActionResult)
def approve_candidate(
    candidate_id: int,
    body: ApproveCandidateRequest,
    user: dict = Depends(require_permission("drafts:publish")),
) -> CandidateActionResult:
    result = approve_taxonomy_candidate(
        candidate_id,
        category=body.category,
        skill_type=body.skill_type,
        family=body.family,
        seniority=body.seniority,
        reviewed_by=user.get("id"),
    )
    return CandidateActionResult(ok=result.get("approved", False), term=result.get("term"), reason=result.get("reason"))


@router.post("/taxonomy-candidates/{candidate_id}/reject", response_model=CandidateActionResult)
def reject_candidate(
    candidate_id: int,
    user: dict = Depends(require_permission("drafts:publish")),
) -> CandidateActionResult:
    result = reject_taxonomy_candidate(candidate_id, reviewed_by=user.get("id"))
    return CandidateActionResult(ok=result.get("rejected", False), term=result.get("term"), reason=result.get("reason"))


class BulkCandidateActionRequest(BaseModel):
    candidate_ids: list[int]


class BulkCandidateActionResult(BaseModel):
    ok_count: int
    ok_terms: list[str]
    failed: list[dict]


@router.post("/taxonomy-candidates/bulk-approve", response_model=BulkCandidateActionResult)
def bulk_approve_candidates(
    body: BulkCandidateActionRequest,
    user: dict = Depends(require_permission("drafts:publish")),
) -> BulkCandidateActionResult:
    result = bulk_approve_taxonomy_candidates(body.candidate_ids, reviewed_by=user.get("id"))
    return BulkCandidateActionResult(
        ok_count=result["approved_count"], ok_terms=result["approved_terms"], failed=result["failed"]
    )


@router.post("/taxonomy-candidates/bulk-reject", response_model=BulkCandidateActionResult)
def bulk_reject_candidates(
    body: BulkCandidateActionRequest,
    user: dict = Depends(require_permission("drafts:publish")),
) -> BulkCandidateActionResult:
    result = bulk_reject_taxonomy_candidates(body.candidate_ids, reviewed_by=user.get("id"))
    return BulkCandidateActionResult(
        ok_count=result["rejected_count"], ok_terms=result["rejected_terms"], failed=result["failed"]
    )


class UpdateSkillDescriptionRequest(BaseModel):
    name: str
    description: str


class UpdateSkillDescriptionResult(BaseModel):
    updated: bool
    reason: str | None = None


@router.patch("/taxonomy/skills/description", response_model=UpdateSkillDescriptionResult)
def edit_skill_description(
    body: UpdateSkillDescriptionRequest,
    user: dict = Depends(require_permission("drafts:publish")),
) -> UpdateSkillDescriptionResult:
    """The Skills taxonomy page's inline edit. name+body rather than a
    path param -- skill names can contain characters ("C++", ".NET")
    that are needlessly fragile to URL-encode/decode correctly for what
    is already a POST-shaped admin action.
    """
    result = update_skill_description(body.name, body.description, edited_by=user.get("id"))
    return UpdateSkillDescriptionResult(updated=result.get("updated", False), reason=result.get("reason"))


class UpdateJobTitleRequest(BaseModel):
    current_title: str
    new_title: str | None = None
    family: str | None = None
    seniority: str | None = None


class UpdateJobTitleResult(BaseModel):
    updated: bool
    title: str | None = None
    reason: str | None = None


@router.patch("/taxonomy/job-titles", response_model=UpdateJobTitleResult)
def edit_job_title(
    body: UpdateJobTitleRequest,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> UpdateJobTitleResult:
    """The Job titles taxonomy page's inline edit -- rename a title, or
    reclassify its family/seniority (the common case: fixing the backlog
    of titles that landed as family="Unclassified" on approval). Body
    rather than a path param, same reasoning as the skill description
    endpoint above -- title text can contain characters fragile to
    URL-encode. A rename that would collide with a different existing
    title is refused, not silently merged.
    """
    result = update_canonical_job_title(
        current_title=body.current_title,
        new_title=body.new_title,
        family=body.family,
        seniority=body.seniority,
    )
    return UpdateJobTitleResult(
        updated=result.get("updated", False), title=result.get("title"), reason=result.get("reason")
    )


class BulkSetJobTitleFamilyRequest(BaseModel):
    titles: list[str]
    family: str


class BulkSetJobTitleFamilyResult(BaseModel):
    updated_count: int
    updated_titles: list[str]


@router.post("/taxonomy/job-titles/bulk-set-family", response_model=BulkSetJobTitleFamilyResult)
def bulk_set_job_title_family_endpoint(
    body: BulkSetJobTitleFamilyRequest,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> BulkSetJobTitleFamilyResult:
    """Reclassifies several selected titles' family in one call -- the
    Job titles page's bulk action for clearing the "Unclassified"
    backlog without editing each title alone.
    """
    result = bulk_set_job_title_family(body.titles, body.family)
    return BulkSetJobTitleFamilyResult(
        updated_count=result["updated_count"], updated_titles=result["updated_titles"]
    )
