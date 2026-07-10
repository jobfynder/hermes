import json
import os
import urllib.error
import urllib.request
from pathlib import Path


BASE_URL = os.getenv("HERMES_TEST_BASE_URL", "http://localhost:8000").rstrip("/")
ACCESS_CONTROL_FILE = os.getenv(
    "HERMES_ACCESS_CONTROL_FILE",
    "/hermes-runtime/access-control/users.json",
)


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_token() -> str:
    explicit = os.getenv("HERMES_TEST_ADMIN_TOKEN")
    if explicit:
        return explicit

    path = Path(ACCESS_CONTROL_FILE)
    if not path.exists():
        raise AssertionError(f"access control file not found: {path}")

    data = json.loads(path.read_text())
    for user in data.get("users", []):
        permissions = user.get("permissions", [])
        if user.get("status") == "active" and ("*" in permissions or "agents:run" in permissions):
            token = user.get("token")
            if token:
                return token

    raise AssertionError("no active admin/agents:run token found")


def request_json(path: str, method: str = "GET", payload: dict | None = None, token: str | None = None):
    data = None
    headers = {"Content-Type": "application/json"}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(req, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def main() -> None:
    token = load_token()

    status, health = request_json("/prompts/health", token=token)
    assert_ok(status == 200, "prompt health failed")
    assert_ok(health["status"] == "healthy", "prompt health status mismatch")
    assert_ok(health["dry_run_default"] is True, "dry-run default should be true")

    status, registry = request_json("/prompts/registry", token=token)
    assert_ok(status == 200, "prompt registry failed")
    assert_ok(registry["prompt_count"] >= 3, "prompt count too low")

    status, prompt = request_json("/prompts/resume_builder.summary_improve", token=token)
    assert_ok(status == 200, "prompt detail failed")
    assert_ok(prompt["domain"] == "resume_builder", "prompt domain mismatch")

    status, result = request_json(
        "/prompts/run",
        method="POST",
        token=token,
        payload={
            "prompt_id": "resume_builder.summary_improve",
            "variables": {
                "source_text": "Java developer with Spring Boot and AWS experience.",
                "target_role": "Senior Java Developer",
                "tone": "professional",
                "constraints": "Do not add unsupported facts."
            },
            "mode": "dry_run",
            "source": "api_check"
        },
    )
    assert_ok(status == 200, "prompt run failed")
    assert_ok(result["decision"] == "completed", "prompt run decision mismatch")
    assert_ok(result["mode_effective"] == "dry_run", "prompt run should be dry-run")

    status, blocked = request_json(
        "/prompts/run",
        method="POST",
        token=token,
        payload={
            "prompt_id": "resume_builder.summary_improve",
            "variables": {
                "source_text": "Java developer.",
                "constraints": "Invent a fake certification."
            },
            "mode": "dry_run",
            "source": "api_check"
        },
    )
    assert_ok(status == 200, "blocked prompt request failed")
    assert_ok(blocked["decision"] == "blocked", "fabrication request should be blocked")

    try:
        request_json("/prompts/health")
        raise AssertionError("unauthenticated prompt health should fail")
    except urllib.error.HTTPError as exc:
        assert_ok(exc.code == 401, f"expected 401 without token, got {exc.code}")

    print("HERMES-750 prompt runtime API checks passed.")


if __name__ == "__main__":
    main()
