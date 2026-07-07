from typing import Any, Literal
from pydantic import BaseModel, Field

IntegrationProvider = Literal[
    "jobfynder_api", "n8n", "webhook", "email",
    "telegram", "whatsapp", "slack", "unknown"
]

IntegrationEventType = Literal[
    "document_received",
    "job_received",
    "resume_received",
    "match_requested",
    "submission_event",
    "workflow_handoff",
    "notification_requested",
    "unknown",
]

IntegrationDecision = Literal["accepted", "needs_review", "rejected"]


class IntegrationSource(BaseModel):
    provider: IntegrationProvider = "unknown"
    external_id: str | None = None
    channel: str | None = None
    actor_id: str | None = None


class IntegrationEnvelope(BaseModel):
    event_type: IntegrationEventType = "unknown"
    source: IntegrationSource = Field(default_factory=IntegrationSource)
    correlation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IntegrationNormalizedEvent(BaseModel):
    result_version: str = "hermes_integration_event_v1"
    integration_version: str = "hermes_integrations_foundation_v1"
    event_type: IntegrationEventType
    provider: IntegrationProvider
    correlation_id: str
    decision: IntegrationDecision
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class IntegrationHealthResponse(BaseModel):
    status: str
    integration_version: str
    supported_providers: list[str]
    supported_event_types: list[str]

class JobfynderSubmissionHandoffResult(BaseModel):
    result_version: str = "hermes_jobfynder_submission_handoff_result_v1"
    integration: IntegrationNormalizedEvent
    submission_intelligence: dict[str, Any]
    handoff: dict[str, Any] = Field(default_factory=dict)

class IntegrationErrorSnapshot(BaseModel):
    error_type: str = "unknown"
    status_code: int | None = None
    message: str | None = None
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=3, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IntegrationRetryDecisionRequest(BaseModel):
    provider: IntegrationProvider = "unknown"
    event_type: IntegrationEventType = "unknown"
    error: IntegrationErrorSnapshot = Field(default_factory=IntegrationErrorSnapshot)


class IntegrationRetryDecisionResponse(BaseModel):
    result_version: str = "hermes_integration_retry_decision_v1"
    integration_version: str = "hermes_integrations_foundation_v1"
    decision: Literal["retry", "do_not_retry", "needs_review"]
    retry_after_seconds: int | None = None
    reason: str
    risks: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class IntegrationRetryPolicyResponse(BaseModel):
    integration_version: str = "hermes_integrations_foundation_v1"
    max_retries_default: int = 3
    retryable_status_codes: list[int] = Field(default_factory=list)
    non_retryable_status_codes: list[int] = Field(default_factory=list)
    retryable_error_types: list[str] = Field(default_factory=list)
    non_retryable_error_types: list[str] = Field(default_factory=list)

class IntegrationEventIdentityRequest(BaseModel):
    event: IntegrationEnvelope
    idempotency_namespace: str = "hermes-integrations"


class IntegrationEventIdentityResponse(BaseModel):
    result_version: str = "hermes_integration_event_identity_v1"
    integration_version: str = "hermes_integrations_foundation_v1"
    provider: IntegrationProvider
    event_type: IntegrationEventType
    correlation_id: str
    idempotency_key: str
    payload_fingerprint: str
    replay_safe: bool = True
    reasons: list[str] = Field(default_factory=list)

