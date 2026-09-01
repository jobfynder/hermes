from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException

from app.email_parsing.blocklist import add_block, list_blocks, remove_block
from app.security.rbac import require_permission
from app.understanding.taxonomy.candidates import (
    approve_taxonomy_candidate,
    auto_classify_unclassified_job_titles,
    bulk_approve_taxonomy_candidates,
    bulk_reject_taxonomy_candidates,
    edit_taxonomy_candidate,
    list_taxonomy_candidates,
    reject_taxonomy_candidate,
    suggest_job_title_family,
    update_skill_description,
)
from app.understanding.taxonomy.loader import (
    bulk_backfill_related_titles,
    bulk_delete_job_titles,
    bulk_delete_skills,
    bulk_set_job_title_family,
    bulk_set_skill_category,
    delete_canonical_job_title,
    delete_canonical_skill,
    update_canonical_job_title,
    update_canonical_skill,
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
    # Used when approving a signal_type='skill' candidate.
    category: str = "Tool/Technology"
    skill_type: str = "tool"
    # Used when approving a signal_type='job_title' candidate. family=None
    # (not "Unclassified") is the default so approve_taxonomy_candidate's
    # own auto-classification runs unless a caller explicitly overrides
    # it -- see that function's docstring.
    family: str | None = None
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


class UpdateSkillRequest(BaseModel):
    current_name: str
    new_name: str | None = None
    category: str | None = None


class UpdateSkillResult(BaseModel):
    updated: bool
    name: str | None = None
    reason: str | None = None


@router.patch("/taxonomy/skills", response_model=UpdateSkillResult)
def edit_skill(
    body: UpdateSkillRequest,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> UpdateSkillResult:
    """The Skills taxonomy page's rename/recategorize edit -- same
    duplicate-collision guard and old-name-kept-as-alias behavior as
    edit_job_title below. Separate from edit_skill_description, which
    only ever touches the description field.
    """
    result = update_canonical_skill(
        current_name=body.current_name,
        new_name=body.new_name,
        category=body.category,
    )
    return UpdateSkillResult(updated=result.get("updated", False), name=result.get("name"), reason=result.get("reason"))


class DeleteSkillRequest(BaseModel):
    name: str


class DeleteSkillResult(BaseModel):
    deleted: bool
    name: str | None = None
    reason: str | None = None


@router.post("/taxonomy/skills/delete", response_model=DeleteSkillResult)
def delete_skill_endpoint(
    body: DeleteSkillRequest,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> DeleteSkillResult:
    """POST rather than DELETE -- skill names ("C++", ".NET") are fragile
    to URL-encode reliably, same reasoning as the other name-bearing
    taxonomy endpoints in this file. Permanently removes the skill,
    unlike a rename it does not keep the old name as an alias.
    """
    result = delete_canonical_skill(body.name)
    return DeleteSkillResult(deleted=result.get("deleted", False), name=result.get("name"), reason=result.get("reason"))


class BulkDeleteSkillsRequest(BaseModel):
    names: list[str]


class BulkDeleteSkillsResult(BaseModel):
    deleted_count: int
    deleted_names: list[str]


@router.post("/taxonomy/skills/bulk-delete", response_model=BulkDeleteSkillsResult)
def bulk_delete_skills_endpoint(
    body: BulkDeleteSkillsRequest,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> BulkDeleteSkillsResult:
    result = bulk_delete_skills(body.names)
    return BulkDeleteSkillsResult(deleted_count=result["deleted_count"], deleted_names=result["deleted_names"])


class BulkSetSkillCategoryRequest(BaseModel):
    names: list[str]
    category: str


class BulkSetSkillCategoryResult(BaseModel):
    updated_count: int
    updated_names: list[str]


@router.post("/taxonomy/skills/bulk-set-category", response_model=BulkSetSkillCategoryResult)
def bulk_set_skill_category_endpoint(
    body: BulkSetSkillCategoryRequest,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> BulkSetSkillCategoryResult:
    """The Skills page's bulk-edit action -- reclassify several selected
    skills' category in one write, same pattern as the job titles page's
    bulk-set-family.
    """
    result = bulk_set_skill_category(body.names, body.category)
    return BulkSetSkillCategoryResult(updated_count=result["updated_count"], updated_names=result["updated_names"])


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


class SuggestJobTitleFamilyRequest(BaseModel):
    title: str


class SuggestJobTitleFamilyResult(BaseModel):
    family: str
    method: str


@router.post("/taxonomy/job-titles/suggest-family", response_model=SuggestJobTitleFamilyResult)
def suggest_job_title_family_endpoint(
    body: SuggestJobTitleFamilyRequest,
    _user: dict = Depends(require_permission("drafts:read")),
) -> SuggestJobTitleFamilyResult:
    """The Job titles page's per-row "Suggest" button -- classifies
    without writing anything, so a reviewer can see the suggestion and
    still change it before saving.
    """
    result = suggest_job_title_family(body.title)
    return SuggestJobTitleFamilyResult(family=result["family"], method=result["method"])


class AutoClassifyResultItem(BaseModel):
    title: str
    family: str
    method: str


class AutoClassifyJobTitlesResult(BaseModel):
    checked_count: int
    classified_count: int
    still_unclassified_count: int
    results: list[AutoClassifyResultItem]


@router.post("/taxonomy/job-titles/auto-classify", response_model=AutoClassifyJobTitlesResult)
def auto_classify_job_titles_endpoint(
    _user: dict = Depends(require_permission("drafts:publish")),
) -> AutoClassifyJobTitlesResult:
    """The Job titles page's "Auto-classify unclassified" bulk action --
    runs every family="Unclassified" title through classify_job_title_family
    (deterministic keyword rules first, LLM only as a fallback) and
    applies whatever it could place in one write.
    """
    result = auto_classify_unclassified_job_titles()
    return AutoClassifyJobTitlesResult(**result)


class BackfillRelatedTitlesResult(BaseModel):
    checked_count: int
    backfilled_count: int
    backfilled_titles: list[str]


@router.post("/taxonomy/job-titles/backfill-related-titles", response_model=BackfillRelatedTitlesResult)
def backfill_related_titles_endpoint(
    _user: dict = Depends(require_permission("drafts:publish")),
) -> BackfillRelatedTitlesResult:
    """The Job titles page's "Fill in related titles" bulk action --
    deterministic token-overlap match (no LLM, see
    compute_related_job_titles), for the backlog of titles added before
    related_titles was computed automatically on approval. Skips any
    title that already has related titles set.
    """
    result = bulk_backfill_related_titles()
    return BackfillRelatedTitlesResult(**result)


class DeleteJobTitleRequest(BaseModel):
    title: str


class DeleteJobTitleResult(BaseModel):
    deleted: bool
    title: str | None = None
    reason: str | None = None


@router.post("/taxonomy/job-titles/delete", response_model=DeleteJobTitleResult)
def delete_job_title_endpoint(
    body: DeleteJobTitleRequest,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> DeleteJobTitleResult:
    """Permanently removes a canonical job title -- unlike a rename, does
    not keep the old title as an alias.
    """
    result = delete_canonical_job_title(body.title)
    return DeleteJobTitleResult(
        deleted=result.get("deleted", False), title=result.get("title"), reason=result.get("reason")
    )


class BulkDeleteJobTitlesRequest(BaseModel):
    titles: list[str]


class BulkDeleteJobTitlesResult(BaseModel):
    deleted_count: int
    deleted_titles: list[str]


@router.post("/taxonomy/job-titles/bulk-delete", response_model=BulkDeleteJobTitlesResult)
def bulk_delete_job_titles_endpoint(
    body: BulkDeleteJobTitlesRequest,
    _user: dict = Depends(require_permission("drafts:publish")),
) -> BulkDeleteJobTitlesResult:
    result = bulk_delete_job_titles(body.titles)
    return BulkDeleteJobTitlesResult(deleted_count=result["deleted_count"], deleted_titles=result["deleted_titles"])
