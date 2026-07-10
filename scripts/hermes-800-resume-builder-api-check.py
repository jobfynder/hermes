import json
import os
import urllib.error
import urllib.request
from pathlib import Path


BASE_URL = os.getenv("HERMES_API_BASE_URL", "http://127.0.0.1:8000")
ACCESS_CONTROL_PATH = Path(
    os.getenv(
        "HERMES_ACCESS_CONTROL_PATH",
        "/hermes-runtime/access-control/users.json",
    )
)


def load_token() -> str:
    if not ACCESS_CONTROL_PATH.exists():
        raise AssertionError(
            f"access control file not found: {ACCESS_CONTROL_PATH}"
        )

    payload = json.loads(ACCESS_CONTROL_PATH.read_text())

    users = payload.get("users", [])
    for user in users:
        permissions = set(user.get("permissions", []))

        required_permissions = {
            "resume_builder:read",
            "resume_builder:analyze",
        }

        if "*" in permissions or required_permissions.issubset(permissions):
            token = user.get("token")
            if token:
                return token

    raise AssertionError(
        "no access-control user has the required "
        "resume_builder permissions"
    )


def request_json(
    method: str,
    path: str,
    token: str,
    payload: dict | None = None,
) -> tuple[int, dict]:
    body = None

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(response_body)
        except json.JSONDecodeError:
            parsed = {"raw": response_body}
        return exc.code, parsed


def main() -> None:
    token = load_token()

    status, health = request_json(
        "GET",
        "/resume-builder/health",
        token,
    )
    assert status == 200, (status, health)
    assert health["status"] == "healthy"
    assert health["module"] == "HERMES-800"
    assert health["external_ai_enabled"] is False
    assert health["human_review_required"] is True
    assert health["automatic_publish_allowed"] is False

    status, policy = request_json(
        "GET",
        "/resume-builder/policy",
        token,
    )
    assert status == 200, (status, policy)
    assert policy["fabrication_allowed"] is False
    assert policy["external_ai_enabled"] is False
    assert policy["automatic_publish_allowed"] is False
    assert policy["human_review_required"] is True
    assert policy["prompt_runtime_mode"] == "dry_run"

    status, blocked = request_json(
        "POST",
        "/resume-builder/analyze",
        token,
        {},
    )
    assert status == 200, (status, blocked)
    assert blocked["decision"] == "blocked"
    assert blocked["human_review_required"] is True
    assert any(
        issue["code"] == "resume_content_required"
        for issue in blocked["issues"]
    )

    status, review = request_json(
        "POST",
        "/resume-builder/analyze",
        token,
        {
            "sections": [
                {
                    "section_id": "summary",
                    "section_type": "summary",
                    "content": "Experienced software engineer.",
                }
            ]
        },
    )
    assert status == 200, (status, review)
    assert review["decision"] == "needs_review"
    assert any(
        issue["code"] == "source_traceability_missing"
        for issue in review["issues"]
    )

    status, completed = request_json(
        "POST",
        "/resume-builder/analyze",
        token,
        {
            "source_text": "Experienced software engineer.",
            "sections": [
                {
                    "section_id": "summary",
                    "section_type": "summary",
                    "content": "Experienced software engineer.",
                    "source_references": [
                        {
                            "source_id": "resume-source-1",
                            "source_type": "resume_text",
                            "field_path": "summary",
                            "excerpt": "Experienced software engineer.",
                            "verified": True,
                        }
                    ],
                }
            ],
        },
    )
    assert status == 200, (status, completed)
    assert completed["decision"] == "completed"
    assert completed["human_review_required"] is True
    assert completed["metadata"]["external_ai_used"] is False
    assert completed["metadata"]["prompt_runtime_used"] is False

    print("HERMES-800 resume builder API checks passed.")


if __name__ == "__main__":
    main()
