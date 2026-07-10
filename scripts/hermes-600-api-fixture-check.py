import json
from pathlib import Path

d = Path("docs/hermes-600/api-fixtures")

required = [
    "README.md",
    "integrations-health-response.json",
    "event-normalize-request.json",
    "event-normalize-response.json",
    "event-normalize-needs-review-request.json",
    "event-normalize-needs-review-response.json",
    "jobfynder-submission-handoff-request.json",
    "jobfynder-submission-handoff-response.json",
    "jobfynder-submission-handoff-duplicate-request.json",
    "jobfynder-submission-handoff-duplicate-response.json",
    "event-identity-response.json",
    "event-identity-request.json",
    "retry-decision-response.json",
    "retry-decision-request.json",
    "retry-policy-response.json",
]

missing = [name for name in required if not (d / name).exists()]
if missing:
    raise SystemExit(f"missing fixtures: {missing}")

for p in sorted(d.glob("*.json")):
    data = json.loads(p.read_text())
    if not isinstance(data, dict):
        raise SystemExit(f"fixture is not a JSON object: {p}")
    print("valid:", p.name)

health = json.loads((d / "integrations-health-response.json").read_text())
assert health["integration_version"] == "hermes_integrations_foundation_v1"

handoff = json.loads((d / "jobfynder-submission-handoff-response.json").read_text())
assert handoff["result_version"] == "hermes_jobfynder_submission_handoff_result_v1"
assert handoff["submission_intelligence"]["recommended_stage"] == "matched"

dup = json.loads((d / "jobfynder-submission-handoff-duplicate-response.json").read_text())
assert dup["submission_intelligence"]["recommended_stage"] == "duplicate_risk"
assert dup["submission_intelligence"]["conflicts"]


retry_policy = json.loads((d / "retry-policy-response.json").read_text())
assert retry_policy["integration_version"] == "hermes_integrations_foundation_v1"
assert 429 in retry_policy["retryable_status_codes"]
assert 422 in retry_policy["non_retryable_status_codes"]

retry_decision = json.loads((d / "retry-decision-response.json").read_text())
assert retry_decision["result_version"] == "hermes_integration_retry_decision_v1"
assert retry_decision["decision"] == "retry"

identity = json.loads((d / "event-identity-response.json").read_text())
assert identity["result_version"] == "hermes_integration_event_identity_v1"
assert identity["provider"] == "jobfynder_api"
assert identity["event_type"] == "workflow_handoff"
assert identity["replay_safe"] is True

print("HERMES-600 API fixture validation passed.")
