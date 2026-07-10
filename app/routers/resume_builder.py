from fastapi import APIRouter, Depends

from app.resume_builder.models import (
    ResumeBuilderHealthResponse,
    ResumeBuilderResult,
    ResumeBuilderSafetyPolicy,
    ResumeDocumentInput,
)
from app.resume_builder.service import (
    analyze_resume_document,
    get_resume_builder_health,
    get_resume_builder_policy,
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
