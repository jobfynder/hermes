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

policy = get("/integrations/retry-policy")
assert policy["integration_version"] == "hermes_integrations_foundation_v1"
assert 429 in policy["retryable_status_codes"]
assert 422 in policy["non_retryable_status_codes"]

retry = post("/integrations/retry-decision", {
    "provider": "jobfynder_api",
    "event_type": "workflow_handoff",
    "error": {
        "error_type": "timeout",
        "status_code": 504,
        "retry_count": 1,
        "max_retries": 3
    }
})
assert retry["decision"] == "retry"

stop = post("/integrations/retry-decision", {
    "provider": "jobfynder_api",
    "event_type": "workflow_handoff",
    "error": {
        "error_type": "validation_error",
        "status_code": 422,
        "retry_count": 0,
        "max_retries": 3
    }
})
assert stop["decision"] == "do_not_retry"

review = post("/integrations/retry-decision", {
    "error": {
        "error_type": "unknown_vendor_error",
        "retry_count": 0,
        "max_retries": 3
    }
})
assert review["decision"] == "needs_review"

openapi = get("/openapi.json")
assert "/integrations/retry-policy" in openapi["paths"]
assert "/integrations/retry-decision" in openapi["paths"]

print("HERMES-600 retry API checks passed.")
