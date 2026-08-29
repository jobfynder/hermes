from fastapi import APIRouter, Depends

from app.contracts.envelope import HermesCapabilityEnvelope, build_envelope
from app.security.rbac import require_permission

from app.submission_intelligence.adapters import build_submission_intelligence_request_from_handoff
from app.submission_intelligence.extraction import extract_submission_status, extract_tracker_update
from app.submission_intelligence.lifecycle import workflow_policy
from app.submission_intelligence.models import (
    SubmissionHandoffEvaluationRequest,
    SubmissionIntelligenceRequest,
    SubmissionIntelligenceResult,
    SubmissionStatusExtractRequest,
    SubmissionStatusExtractResponse,
    SubmissionWorkflowPolicyResponse,
    TrackerUpdateExtractRequest,
    TrackerUpdateExtractResponse,
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
    user: dict = Depends(require_permission("submissions:evaluate")),
) -> SubmissionIntelligenceResult:
    return evaluate_submission_intelligence(request)

@router.post("/evaluate/from-handoff", response_model=SubmissionIntelligenceResult)
def evaluate_submission_from_handoff(
    request: SubmissionHandoffEvaluationRequest,
    user: dict = Depends(require_permission("submissions:evaluate")),
) -> SubmissionIntelligenceResult:
    submission_request = build_submission_intelligence_request_from_handoff(request)
    return evaluate_submission_intelligence(submission_request)



@router.post("/tracker-update/extract", response_model=HermesCapabilityEnvelope)
def extract_tracker_update_endpoint(
    request: TrackerUpdateExtractRequest,
) -> HermesCapabilityEnvelope:
    result = extract_tracker_update(
        message=request.message,
        tracker_context=request.tracker_context,
        allowed_stages=request.allowed_stages,
    )
    llm_fallback = result.get("llm_fallback") or {}
    return build_envelope(
        capability="hermes.workflow.extract_tracker_update",
        structured_data={"proposed_stage": result["proposed_stage"]},
        confidence=result["confidence"],
        llm_required=bool(llm_fallback.get("used")),
        llm_prompt_name="jf.job-tracker.update.extract" if llm_fallback.get("used") else None,
        warnings=result["reasons"],
    )


@router.post("/status/extract", response_model=HermesCapabilityEnvelope)
def extract_submission_status_endpoint(
    request: SubmissionStatusExtractRequest,
) -> HermesCapabilityEnvelope:
    result = extract_submission_status(
        message=request.message,
        submission_context=request.submission_context,
        statuses=request.statuses,
    )
    llm_fallback = result.get("llm_fallback") or {}
    return build_envelope(
        capability="hermes.workflow.extract_submission_status",
        structured_data={"proposed_status": result["proposed_status"]},
        confidence=result["confidence"],
        llm_required=bool(llm_fallback.get("used")),
        llm_prompt_name="jf.submissions.status.extract" if llm_fallback.get("used") else None,
        warnings=result["reasons"],
    )
