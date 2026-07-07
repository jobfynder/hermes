#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.understanding.models import RawDocument
from app.understanding.service import understand_document


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    print("HERMES-400 understanding taxonomy integration check started")

    resume = RawDocument(
        document_kind="resume",
        filename="sample-resume.txt",
        content=(
            "Senior Java Engineer with 8 years of Core Java, SpringBoot, AWS, "
            "K8s, Docker, PostgreSQL, and RESTful API experience."
        ),
    )

    result = understand_document(resume)
    structured = result.structured_data

    require("taxonomy_signals" in structured, "structured_data missing taxonomy_signals")
    require("normalized_skills" in structured, "structured_data missing normalized_skills")
    require("normalized_job_titles" in structured, "structured_data missing normalized_job_titles")

    normalized_skills = set(structured["normalized_skills"])
    normalized_titles = set(structured["normalized_job_titles"])

    require("Java" in normalized_skills, "Java missing from normalized_skills")
    require("Spring Boot" in normalized_skills, "Spring Boot missing from normalized_skills")
    require("AWS" in normalized_skills, "AWS missing from normalized_skills")
    require("Kubernetes" in normalized_skills, "Kubernetes missing from normalized_skills")
    require("PostgreSQL" in normalized_skills, "PostgreSQL missing from normalized_skills")
    require("REST API" in normalized_skills, "REST API missing from normalized_skills")

    require("Senior Java Developer" in normalized_titles, "Senior Java Developer missing from normalized_job_titles")

    signals = structured["taxonomy_signals"]
    require(signals.get("result_version") == "hermes_taxonomy_signal_extraction_v1", "taxonomy signal result_version invalid")
    require(signals.get("taxonomy_versions", {}).get("canonical_skills"), "taxonomy canonical skill version missing")
    require(signals.get("taxonomy_versions", {}).get("job_titles"), "taxonomy job title version missing")

    print("OK: taxonomy_signals added to UnderstandingResult.structured_data")
    print("OK: normalized_skills added to UnderstandingResult.structured_data")
    print("OK: normalized_job_titles added to UnderstandingResult.structured_data")
    print("HERMES-400 understanding taxonomy integration check PASSED")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"HERMES-400 understanding taxonomy integration check FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
