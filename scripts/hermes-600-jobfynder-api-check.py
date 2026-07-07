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
    "event_type": "workflow_handoff",
    "source": {
        "provider": "jobfynder_api",
        "external_id": "jobfynder-api-001",
        "channel": "api",
        "actor_id": "recruiter-001"
    },
    "correlation_id": "corr-jobfynder-api-001",
    "payload": {
        "submission_id": "submission-api-001",
        "current_stage": "discovered",
        "requirement": {
            "job_id": "job-api-001",
            "title": "Python Developer",
            "required_skills": ["Python", "FastAPI"]
        },
        "consultant": {
            "consultant_id": "consultant-api-001",
            "name": "Test Consultant",
            "skills": ["Python", "FastAPI"]
        },
        "match_result": {
            "decision": "submit",
            "match_score": 91
        }
    }
}

result = post("/integrations/jobfynder/submission-handoff/evaluate", payload)
assert result["result_version"] == "hermes_jobfynder_submission_handoff_result_v1"
assert result["integration"]["decision"] == "accepted"
assert result["integration"]["correlation_id"] == "corr-jobfynder-api-001"
assert result["submission_intelligence"]["recommended_stage"] == "matched"
assert result["handoff"]["job_id"] == "job-api-001"

dup_payload = payload.copy()
dup_payload["payload"] = dict(payload["payload"])
dup_payload["payload"]["current_stage"] = "matched"
dup_payload["payload"]["existing_submission_keys"] = ["consultant-api-001:job-api-001"]

dup = post("/integrations/jobfynder/submission-handoff/evaluate", dup_payload)
assert dup["submission_intelligence"]["recommended_stage"] == "duplicate_risk"
assert dup["submission_intelligence"]["conflicts"]

openapi = get("/openapi.json")
assert "/integrations/jobfynder/submission-handoff/evaluate" in openapi["paths"]

print("HERMES-600 Jobfynder API checks passed.")
