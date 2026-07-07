import json
import urllib.request

BASE = "http://127.0.0.1:8000"

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read().decode())

def post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        BASE + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())

health = get("/integrations/health")
assert health["status"] == "healthy"
assert "jobfynder_api" in health["supported_providers"]

payload = {
    "event_type": "workflow_handoff",
    "source": {
        "provider": "jobfynder_api",
        "external_id": "jobfynder-event-api-001",
        "channel": "api",
        "actor_id": "user-001"
    },
    "correlation_id": "corr-api-001",
    "payload": {
        "job_id": "job-001",
        "consultant_id": "consultant-001"
    }
}

result = post("/integrations/events/normalize", payload)
assert result["decision"] == "accepted"
assert result["correlation_id"] == "corr-api-001"
assert result["provider"] == "jobfynder_api"

review = post("/integrations/events/normalize", {})
assert review["decision"] == "needs_review"
assert review["risks"]

openapi = get("/openapi.json")
assert "/integrations/health" in openapi["paths"]
assert "/integrations/events/normalize" in openapi["paths"]

print("HERMES-600 integrations API checks passed.")
