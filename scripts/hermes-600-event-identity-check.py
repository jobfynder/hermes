import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.models import IntegrationEnvelope, IntegrationEventIdentityRequest
from app.integrations.service import build_event_identity

payload = {
    "submission_id": "submission-identity-001",
    "job_id": "job-identity-001",
    "consultant_id": "consultant-identity-001",
}

event = IntegrationEnvelope(
    event_type="workflow_handoff",
    source={
        "provider": "jobfynder_api",
        "external_id": "event-identity-001",
        "channel": "api",
        "actor_id": "recruiter-001",
    },
    correlation_id="corr-identity-001",
    payload=payload,
)

first = build_event_identity(IntegrationEventIdentityRequest(event=event))
second = build_event_identity(IntegrationEventIdentityRequest(event=event))

assert first.result_version == "hermes_integration_event_identity_v1"
assert first.provider == "jobfynder_api"
assert first.event_type == "workflow_handoff"
assert first.correlation_id == "corr-identity-001"
assert first.idempotency_key == second.idempotency_key
assert first.payload_fingerprint == second.payload_fingerprint
assert first.replay_safe is True

changed = IntegrationEnvelope(
    event_type="workflow_handoff",
    source={
        "provider": "jobfynder_api",
        "external_id": "event-identity-001",
        "channel": "api",
    },
    correlation_id="corr-identity-001",
    payload={**payload, "job_id": "job-identity-002"},
)

third = build_event_identity(IntegrationEventIdentityRequest(event=changed))
assert third.payload_fingerprint != first.payload_fingerprint
assert third.idempotency_key != first.idempotency_key

print("HERMES-600 event identity checks passed.")
