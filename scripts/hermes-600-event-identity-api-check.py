import json
import os
import urllib.request

BASE = os.environ.get("HERMES_API_BASE_URL", "http://127.0.0.1:8000")

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read().decode())

def post(path, data):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())

payload = {
    "event": {
        "event_type": "workflow_handoff",
        "source": {
            "provider": "jobfynder_api",
            "external_id": "event-identity-api-001",
            "channel": "api",
            "actor_id": "recruiter-001"
        },
        "correlation_id": "corr-identity-api-001",
        "payload": {
            "submission_id": "submission-identity-api-001",
            "job_id": "job-identity-api-001",
            "consultant_id": "consultant-identity-api-001"
        }
    },
    "idempotency_namespace": "jobfynder-api"
}

first = post("/integrations/events/identity", payload)
second = post("/integrations/events/identity", payload)

assert first["result_version"] == "hermes_integration_event_identity_v1"
assert first["integration_version"] == "hermes_integrations_foundation_v1"
assert first["provider"] == "jobfynder_api"
assert first["event_type"] == "workflow_handoff"
assert first["correlation_id"] == "corr-identity-api-001"
assert first["idempotency_key"] == second["idempotency_key"]
assert first["payload_fingerprint"] == second["payload_fingerprint"]
assert first["replay_safe"] is True

changed = json.loads(json.dumps(payload))
changed["event"]["payload"]["job_id"] = "job-identity-api-002"

third = post("/integrations/events/identity", changed)
assert third["payload_fingerprint"] != first["payload_fingerprint"]
assert third["idempotency_key"] != first["idempotency_key"]

openapi = get("/openapi.json")
assert "/integrations/events/identity" in openapi["paths"]

print("HERMES-600 event identity API checks passed.")
