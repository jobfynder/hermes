from fastapi import APIRouter

from app.submission_intelligence.adapters import build_submission_intelligence_request_from_handoff
from app.submission_intelligence.lifecycle import workflow_policy
from app.submission_intelligence.models import (
    SubmissionHandoffEvaluationRequest,
    SubmissionIntelligenceRequest,
    SubmissionIntelligenceResult,
    SubmissionWorkflowPolicyResponse,
)
from app.submission_intelligence.service import evaluate_submission_intelligence


router = APIRouter(
    prefix="/submissions",
    tags=["Submission Intelligence"],
)


@router.get("/workflow-policy", response_model=SubmissionWorkflowPolicyResponse)
def get_submission_workflow_policy() -> SubmissionWorkflowPolicyResponse:
    return SubmissionWorkflowPolicyResponse(**workflow_policy())


@router.post("/evaluate", response_model=SubmissionIntelligenceResult)
def evaluate_submission(
    request: SubmissionIntelligenceRequest,
) -> SubmissionIntelligenceResult:
    return evaluate_submission_intelligence(request)

@router.post("/evaluate/from-handoff", response_model=SubmissionIntelligenceResult)
def evaluate_submission_from_handoff(
    request: SubmissionHandoffEvaluationRequest,
) -> SubmissionIntelligenceResult:
    submission_request = build_submission_intelligence_request_from_handoff(request)
    return evaluate_submission_intelligence(submission_request)

