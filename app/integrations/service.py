from uuid import uuid4

from app.integrations.models import (
    IntegrationEnvelope,
    IntegrationHealthResponse,
    IntegrationNormalizedEvent,
    IntegrationRetryDecisionRequest,
    IntegrationRetryDecisionResponse,
    IntegrationRetryPolicyResponse,
)

INTEGRATION_VERSION = "hermes_integrations_foundation_v1"

SUPPORTED_PROVIDERS = [
    "jobfynder_api", "n8n", "webhook", "email",
    "telegram", "whatsapp", "slack", "unknown",
]

SUPPORTED_EVENT_TYPES = [
    "document_received",
    "job_received",
    "resume_received",
    "match_requested",
    "submission_event",
    "workflow_handoff",
    "notification_requested",
    "unknown",
]


def get_integration_health() -> IntegrationHealthResponse:
    return IntegrationHealthResponse(
        status="healthy",
        integration_version=INTEGRATION_VERSION,
        supported_providers=SUPPORTED_PROVIDERS,
        supported_event_types=SUPPORTED_EVENT_TYPES,
    )


def normalize_integration_event(
    envelope: IntegrationEnvelope,
) -> IntegrationNormalizedEvent:
    reasons: list[str] = []
    risks: list[str] = []

    correlation_id = envelope.correlation_id or f"hermes-{uuid4()}"

    if envelope.source.provider == "unknown":
        risks.append("Integration provider is unknown.")

    if envelope.event_type == "unknown":
        risks.append("Integration event type is unknown.")

    if not envelope.payload:
        risks.append("Integration payload is empty.")

    if risks:
        decision = "needs_review"
    else:
        decision = "accepted"

    reasons.append(f"Received {envelope.event_type} from {envelope.source.provider}.")

    return IntegrationNormalizedEvent(
        event_type=envelope.event_type,
        provider=envelope.source.provider,
        correlation_id=correlation_id,
        decision=decision,
        reasons=reasons,
        risks=risks,
        payload=envelope.payload,
        handoff={
            "source_provider": envelope.source.provider,
            "source_external_id": envelope.source.external_id,
            "channel": envelope.source.channel,
            "actor_id": envelope.source.actor_id,
            "metadata": envelope.metadata,
        },
    )

RETRYABLE_STATUS_CODES = [408, 429, 500, 502, 503, 504]
NON_RETRYABLE_STATUS_CODES = [400, 401, 403, 404, 409, 422]
RETRYABLE_ERROR_TYPES = ["timeout", "rate_limited", "temporary_network", "server_error"]
NON_RETRYABLE_ERROR_TYPES = ["validation_error", "authentication_error", "permission_error", "not_found", "duplicate"]


def get_retry_policy() -> IntegrationRetryPolicyResponse:
    return IntegrationRetryPolicyResponse(
        retryable_status_codes=RETRYABLE_STATUS_CODES,
        non_retryable_status_codes=NON_RETRYABLE_STATUS_CODES,
        retryable_error_types=RETRYABLE_ERROR_TYPES,
        non_retryable_error_types=NON_RETRYABLE_ERROR_TYPES,
    )


def decide_retry(request: IntegrationRetryDecisionRequest) -> IntegrationRetryDecisionResponse:
    error = request.error
    risks: list[str] = []
    next_actions: list[str] = []

    if error.retry_count >= error.max_retries:
        return IntegrationRetryDecisionResponse(
            decision="do_not_retry",
            reason="Maximum retry count reached.",
            risks=["Further retries may create duplicate work or noisy failures."],
            next_actions=["Move event to manual review or dead-letter queue."],
        )

    if error.status_code in NON_RETRYABLE_STATUS_CODES:
        return IntegrationRetryDecisionResponse(
            decision="do_not_retry",
            reason=f"HTTP {error.status_code} is not retryable.",
            risks=["Payload or authorization likely needs correction."],
            next_actions=["Fix payload, credentials, or permissions before resubmitting."],
        )

    if error.error_type in NON_RETRYABLE_ERROR_TYPES:
        return IntegrationRetryDecisionResponse(
            decision="do_not_retry",
            reason=f"Error type {error.error_type} is not retryable.",
            risks=["Retrying will likely repeat the same failure."],
            next_actions=["Correct the source event before resubmitting."],
        )

    if error.status_code in RETRYABLE_STATUS_CODES or error.error_type in RETRYABLE_ERROR_TYPES:
        retry_after = min(300, 30 * (error.retry_count + 1))
        return IntegrationRetryDecisionResponse(
            decision="retry",
            retry_after_seconds=retry_after,
            reason="Transient integration failure can be retried safely.",
            next_actions=[f"Retry after {retry_after} seconds."],
        )

    risks.append("Unknown error type or status code.")
    next_actions.append("Review the failed integration event before retrying.")

    return IntegrationRetryDecisionResponse(
        decision="needs_review",
        reason="Retry safety could not be determined.",
        risks=risks,
        next_actions=next_actions,
    )

