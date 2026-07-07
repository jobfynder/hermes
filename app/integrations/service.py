from uuid import uuid4

from app.integrations.models import (
    IntegrationEnvelope,
    IntegrationHealthResponse,
    IntegrationNormalizedEvent,
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
