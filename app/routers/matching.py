from fastapi import APIRouter, Depends

from app.matching.models import ResumeToJobMatchRequest, ResumeToJobMatchResult
from app.matching.scorer import evaluate_resume_to_job
from app.security.rbac import require_permission

router = APIRouter(
    prefix="/matching",
    tags=["Matching"],
)


@router.post("/resume-to-job", response_model=ResumeToJobMatchResult)
def resume_to_job_match(
    request: ResumeToJobMatchRequest,
    user: dict = Depends(require_permission("matching:evaluate")),
) -> ResumeToJobMatchResult:
    return evaluate_resume_to_job(request)
