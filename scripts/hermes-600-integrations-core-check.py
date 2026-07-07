import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.models import IntegrationEnvelope, IntegrationSource
from app.integrations.service import get_integration_health, normalize_integration_event


def test_health():
    result = get_integration_health()
    assert result.status == "healthy"
    assert "jobfynder_api" in result.supported_providers
    assert "workflow_handoff" in result.supported_event_types


def test_accepted_event():
    event = IntegrationEnvelope(
        event_type="workflow_handoff",
        source=IntegrationSource(
            provider="jobfynder_api",
            external_id="jobfynder-event-001",
            channel="api",
            actor_id="user-001",
        ),
        correlation_id="corr-001",
        payload={"job_id": "job-001", "consultant_id": "consultant-001"},
    )

    result = normalize_integration_event(event)

    assert result.decision == "accepted"
    assert result.correlation_id == "corr-001"
    assert result.provider == "jobfynder_api"
    assert result.handoff["source_external_id"] == "jobfynder-event-001"


def test_needs_review_event():
    event = IntegrationEnvelope()
    result = normalize_integration_event(event)

    assert result.decision == "needs_review"
    assert result.risks


if __name__ == "__main__":
    test_health()
    test_accepted_event()
    test_needs_review_event()
    print("HERMES-600 integrations core checks passed.")
