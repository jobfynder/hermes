#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.main import app


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    print("HERMES-400 taxonomy API check started")

    client = TestClient(app)

    endpoints = [
        "/understanding/taxonomy/skills",
        "/understanding/taxonomy/skills/canonical",
        "/understanding/taxonomy/skills/aliases",
        "/understanding/taxonomy/job-titles",
        "/understanding/taxonomy/job-title-aliases",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        require(response.status_code == 200, f"{endpoint} returned {response.status_code}")
        payload = response.json()
        require(payload.get("version"), f"{endpoint} missing version")
        require(payload.get("taxonomy_type") or payload.get("skills"), f"{endpoint} missing taxonomy payload")
        print(f"OK: GET {endpoint}")

    response = client.post(
        "/understanding/taxonomy/normalize",
        json={
            "skills": ["JS", "reactjs", "k8s", "unknown-skill-x"],
            "job_titles": ["Sr Java Developer", "SRE", "Bench Sales", "Unknown Future Role"],
        },
    )

    require(response.status_code == 200, f"normalize endpoint returned {response.status_code}")

    payload = response.json()
    require(
        payload.get("result_version") == "hermes_taxonomy_normalization_result_v1",
        "normalize endpoint returned wrong result_version",
    )

    normalized_skills = payload.get("normalized_skills", [])
    normalized_titles = payload.get("normalized_job_titles", [])

    require(normalized_skills[0]["normalized"] == "JavaScript", "JS did not normalize to JavaScript")
    require(normalized_skills[1]["normalized"] == "React", "reactjs did not normalize to React")
    require(normalized_skills[2]["normalized"] == "Kubernetes", "k8s did not normalize to Kubernetes")
    require(normalized_skills[3]["matched"] is False, "unknown skill should not be matched")

    require(normalized_titles[0]["normalized"] == "Senior Java Developer", "Sr Java Developer title failed")
    require(normalized_titles[1]["normalized"] == "Site Reliability Engineer", "SRE title failed")
    require(normalized_titles[2]["normalized"] == "Bench Sales Recruiter", "Bench Sales title failed")
    require(normalized_titles[3]["matched"] is False, "unknown title should not be matched")

    print("OK: POST /understanding/taxonomy/normalize")
    print("HERMES-400 taxonomy API check PASSED")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"HERMES-400 taxonomy API check FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
