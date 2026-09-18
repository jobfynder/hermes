from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.security.rbac import require_permission
from app.skill_intelligence.models import (
    RequirementIntelligenceRequest,
    RequirementIntelligenceResponse,
    ResolveBatchRequest,
    ResolveBatchResponse,
    SkillCardDTO,
)
from app.skill_intelligence.service import (
    extract_requirement_intelligence,
    get_skill,
    resolve_batch,
    search,
)


router = APIRouter(prefix="/skill-intelligence", tags=["Skill Intelligence"])


@router.post("/resolve-batch", response_model=ResolveBatchResponse)
def resolve_skill_batch(
    request: ResolveBatchRequest,
    user: dict = Depends(require_permission("understanding:read")),
):
    return resolve_batch(request.terms)


@router.get("/search", response_model=list[SkillCardDTO])
def search_skills(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=50),
    user: dict = Depends(require_permission("understanding:read")),
):
    return search(q, limit)


@router.get("/skills/{skill_id}", response_model=SkillCardDTO)
def get_skill_card(
    skill_id: str,
    user: dict = Depends(require_permission("understanding:read")),
):
    result = get_skill(skill_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    return result


@router.post("/requirements/extract", response_model=RequirementIntelligenceResponse)
def extract_requirement_skills(
    request: RequirementIntelligenceRequest,
    user: dict = Depends(require_permission("understanding:parse")),
):
    return extract_requirement_intelligence(request.text, request.include_unknown_terms)
