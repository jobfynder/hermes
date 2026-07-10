from fastapi import APIRouter, Depends

from app.resume_builder.models import (
    ResumeBuilderHealthResponse,
    ResumeBuilderResult,
    ResumeBuilderSafetyPolicy,
    ResumeBulletSuggestionRequest,
    ResumeDocumentInput,
    ResumeSkillNormalizationRequest,
    ResumeSkillNormalizationResponse,
    ResumeSuggestionResponse,
    ResumeSummarySuggestionRequest,
)
from app.resume_builder.service import (
    analyze_resume_document,
    get_resume_builder_health,
    suggest_bullet,
    suggest_summary,
    get_resume_builder_policy,
    normalize_resume_skills,
)
from app.security.rbac import require_permission


router = APIRouter(
    prefix="/resume-builder",
    tags=["resume-builder"],
)


@router.get("/health", response_model=ResumeBuilderHealthResponse)
def resume_builder_health(
    _user: dict = Depends(require_permission("resume_builder:read")),
) -> ResumeBuilderHealthResponse:
    return get_resume_builder_health()


@router.get("/policy", response_model=ResumeBuilderSafetyPolicy)
def resume_builder_policy(
    _user: dict = Depends(require_permission("resume_builder:read")),
) -> ResumeBuilderSafetyPolicy:
    return get_resume_builder_policy()


@router.post("/analyze", response_model=ResumeBuilderResult)
def resume_builder_analyze(
    document: ResumeDocumentInput,
    _user: dict = Depends(
        require_permission("resume_builder:analyze")
    ),
) -> ResumeBuilderResult:
    return analyze_resume_document(document)


@router.post(
    "/summary/suggest",
    response_model=ResumeSuggestionResponse,
)
def resume_builder_summary_suggest(
    request: ResumeSummarySuggestionRequest,
    _user: dict = Depends(
        require_permission("resume_builder:suggest")
    ),
) -> ResumeSuggestionResponse:
    return suggest_summary(request)


@router.post(
    "/bullets/suggest",
    response_model=ResumeSuggestionResponse,
)
def resume_builder_bullet_suggest(
    request: ResumeBulletSuggestionRequest,
    _user: dict = Depends(
        require_permission("resume_builder:suggest")
    ),
) -> ResumeSuggestionResponse:
    return suggest_bullet(request)


@router.post(
    "/skills/normalize",
    response_model=ResumeSkillNormalizationResponse,
)
def resume_builder_skills_normalize(
    request: ResumeSkillNormalizationRequest,
    _user: dict = Depends(
        require_permission("resume_builder:analyze")
    ),
) -> ResumeSkillNormalizationResponse:
    return normalize_resume_skills(request)
