from fastapi import APIRouter, Depends

from app.matching.adapters import build_resume_to_job_request_from_understanding
from app.matching.models import ResumeToJobFromUnderstandingRequest, ResumeToJobMatchRequest, ResumeToJobMatchResult
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

@router.post("/resume-to-job/from-understanding", response_model=ResumeToJobMatchResult)
def resume_to_job_match_from_understanding(
    request: ResumeToJobFromUnderstandingRequest,
    user: dict = Depends(require_permission("matching:evaluate")),
) -> ResumeToJobMatchResult:
    match_request = build_resume_to_job_request_from_understanding(
        resume_result=request.resume_result,
        job_result=request.job_result,
    )
    return evaluate_resume_to_job(match_request)
