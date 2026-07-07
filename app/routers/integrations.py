from fastapi import APIRouter

from app.integrations.jobfynder import build_submission_request_from_jobfynder_event
from app.submission_intelligence.service import evaluate_submission_intelligence
from app.integrations.models import (
    IntegrationEnvelope,
    IntegrationHealthResponse,
    IntegrationNormalizedEvent,
    JobfynderSubmissionHandoffResult,
)
from app.integrations.service import (
    get_integration_health,
    normalize_integration_event,
)

router = APIRouter(prefix="/integrations", tags=["Integrations"])


@router.get("/health", response_model=IntegrationHealthResponse)
def integrations_health() -> IntegrationHealthResponse:
    return get_integration_health()


@router.post("/events/normalize", response_model=IntegrationNormalizedEvent)
def normalize_event(
    envelope: IntegrationEnvelope,
) -> IntegrationNormalizedEvent:
    return normalize_integration_event(envelope)

@router.post(
    "/jobfynder/submission-handoff/evaluate",
    response_model=JobfynderSubmissionHandoffResult,
)
def evaluate_jobfynder_submission_handoff(
    envelope: IntegrationEnvelope,
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

