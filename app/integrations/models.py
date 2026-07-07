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

