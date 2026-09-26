from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.security.rbac import require_permission
from app.skill_intelligence.models import (
    RequirementIntelligenceRequest,
    RequirementIntelligenceResponse,
    ResolveBatchRequest,
    ResolveBatchResponse,
    SkillCardDTO,
    SkillSuggestionRequest,
    SkillSuggestionResponse,
)
from app.skill_intelligence.service import (
    extract_requirement_intelligence,
    get_skill,
    resolve_batch,
    search,
)
from app.skill_intelligence.suggestions import submit_skill_suggestion


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


@router.post("/suggestions", response_model=SkillSuggestionResponse)
def create_skill_suggestion(
    request: SkillSuggestionRequest,
    user: dict = Depends(require_permission("understanding:parse")),
):
    """Add review evidence only; never mutate the canonical taxonomy."""
    try:
        return submit_skill_suggestion(**request.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
