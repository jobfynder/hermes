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


def normalized_names(items: list[dict[str, object]]) -> set[str]:
    return {str(item["normalized"]) for item in items}


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


    snapshot_response = client.get("/understanding/taxonomy/snapshot")
    require(snapshot_response.status_code == 200, f"snapshot endpoint returned {snapshot_response.status_code}")

    snapshot = snapshot_response.json()
    require(
        snapshot.get("result_version") == "hermes_taxonomy_snapshot_v1",
        "snapshot endpoint returned wrong result_version",
    )
    require(
        snapshot.get("snapshot_name") == "hermes-400-taxonomy-foundation-v1",
        "snapshot endpoint returned wrong snapshot_name",
    )
    require(snapshot.get("validation_status") == "passed", "snapshot validation_status should be passed")

    counts = snapshot.get("counts", {})
    for key in ["canonical_skills", "skill_aliases", "job_titles", "title_aliases"]:
        require(counts.get(key, 0) > 0, f"snapshot count missing for {key}")

    print("OK: GET /understanding/taxonomy/snapshot details")

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

    response = client.post(
        "/understanding/taxonomy/extract-signals",
        json={
            "text": (
                "React UI Developer needed with JavaScript, ReactJS, TypeScript, "
                "AWS, K8s, PostgreSQL, and RESTful API. SRE exposure is a plus."
            )
        },
    )

    require(response.status_code == 200, f"extract-signals endpoint returned {response.status_code}")

    signal_payload = response.json()
    require(
        signal_payload.get("result_version") == "hermes_taxonomy_signal_extraction_v1",
        "extract-signals endpoint returned wrong result_version",
    )

    skill_names = normalized_names(signal_payload.get("skills", []))
    title_names = normalized_names(signal_payload.get("job_titles", []))

    require("JavaScript" in skill_names, "JavaScript signal missing")
    require("React" in skill_names, "React signal missing")
    require("TypeScript" in skill_names, "TypeScript signal missing")
    require("AWS" in skill_names, "AWS signal missing")
    require("Kubernetes" in skill_names, "Kubernetes signal missing")
    require("PostgreSQL" in skill_names, "PostgreSQL signal missing")
    require("REST API" in skill_names, "REST API signal missing")
    require("Frontend React Developer" in title_names, "Frontend React Developer title signal missing")
    require("Site Reliability Engineer" in title_names, "Site Reliability Engineer title signal missing")

    print("OK: POST /understanding/taxonomy/extract-signals")

    response = client.post(
        "/understanding/taxonomy/suggestions",
        json={
            "skills": ["JavaScript", "Vector Database", "RAG Pipeline"],
            "job_titles": ["SRE", "Prompt Engineer"],
            "source_context": "api-check",
        },
    )

    require(response.status_code == 200, f"suggestions endpoint returned {response.status_code}")

    suggestions_payload = response.json()
    require(
        suggestions_payload.get("result_version") == "hermes_taxonomy_suggestion_queue_v1",
        "suggestions endpoint returned wrong result_version",
    )

    suggestions = suggestions_payload.get("suggestions", [])
    observed = {
        (str(item["suggestion_type"]), str(item["observed_term"]))
        for item in suggestions
    }

    require(("skill", "Vector Database") in observed, "Vector Database suggestion missing")
    require(("skill", "RAG Pipeline") in observed, "RAG Pipeline suggestion missing")
    require(("job_title", "Prompt Engineer") in observed, "Prompt Engineer suggestion missing")
    require(("skill", "JavaScript") not in observed, "known JavaScript should not be suggested")
    require(("job_title", "SRE") not in observed, "known SRE should not be suggested")
    require(suggestions_payload.get("accepted_count") == 0, "suggestions endpoint should not auto-approve")
    require(
        suggestions_payload.get("review_required_count") == len(suggestions),
        "suggestions review_required_count mismatch",
    )

    print("OK: POST /understanding/taxonomy/suggestions")

    print("HERMES-400 taxonomy API check PASSED")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"HERMES-400 taxonomy API check FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
