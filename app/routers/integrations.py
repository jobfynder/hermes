from app.security.rbac import require_service_permission
from fastapi import APIRouter, Depends

from app.integrations.jobfynder import build_submission_request_from_jobfynder_event
from app.submission_intelligence.service import evaluate_submission_intelligence
from app.integrations.models import (
    IntegrationEnvelope,
    IntegrationHealthResponse,
    IntegrationNormalizedEvent,
    JobfynderSubmissionHandoffResult,
    IntegrationRetryDecisionRequest,
    IntegrationRetryDecisionResponse,
    IntegrationRetryPolicyResponse,
    IntegrationEventIdentityRequest,
    IntegrationEventIdentityResponse,
)
from app.integrations.service import (
    get_integration_health,
    normalize_integration_event,
    get_retry_policy,
    decide_retry,
    build_event_identity,
)

router = APIRouter(prefix="/integrations", tags=["Integrations"])


@router.get("/health", response_model=IntegrationHealthResponse)
def integrations_health(_principal: dict = Depends(require_service_permission("submissions:evaluate"))) -> IntegrationHealthResponse:
    return get_integration_health()


@router.post("/events/normalize", response_model=IntegrationNormalizedEvent)
def normalize_event(
    envelope: IntegrationEnvelope,
    _principal: dict = Depends(require_service_permission("submissions:evaluate")),
) -> IntegrationNormalizedEvent:
    return normalize_integration_event(envelope)

@router.post(
    "/jobfynder/submission-handoff/evaluate",
    response_model=JobfynderSubmissionHandoffResult,
)
def evaluate_jobfynder_submission_handoff(
    envelope: IntegrationEnvelope,
    _principal: dict = Depends(require_service_permission("submissions:evaluate")),
) -> JobfynderSubmissionHandoffResult:
    integration_event = normalize_integration_event(envelope)
    submission_request = build_submission_request_from_jobfynder_event(envelope)
    submission_result = evaluate_submission_intelligence(submission_request)

    return JobfynderSubmissionHandoffResult(
        integration=integration_event,
        submission_intelligence=submission_result.model_dump(),
        handoff={
            "source": "hermes-600-jobfynder-integration",
            "correlation_id": integration_event.correlation_id,
            "submission_id": submission_request.submission_id,
            "job_id": submission_request.requirement.job_id,
            "consultant_id": submission_request.consultant.consultant_id,
        },
    )

@router.get("/retry-policy", response_model=IntegrationRetryPolicyResponse)
def integrations_retry_policy(_principal: dict = Depends(require_service_permission("submissions:evaluate"))) -> IntegrationRetryPolicyResponse:
    return get_retry_policy()


@router.post("/retry-decision", response_model=IntegrationRetryDecisionResponse)
def integrations_retry_decision(
    request: IntegrationRetryDecisionRequest,
    _principal: dict = Depends(require_service_permission("submissions:evaluate")),
) -> IntegrationRetryDecisionResponse:
    return decide_retry(request)

@router.post("/events/identity", response_model=IntegrationEventIdentityResponse)
def integrations_event_identity(
    request: IntegrationEventIdentityRequest,
    _principal: dict = Depends(require_service_permission("submissions:evaluate")),
) -> IntegrationEventIdentityResponse:
    return build_event_identity(request)

