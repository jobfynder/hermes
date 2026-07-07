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

print("HERMES-600 API fixture validation passed.")
