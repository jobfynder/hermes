#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.understanding.taxonomy.suggestions import build_taxonomy_suggestions


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    print("HERMES-400 taxonomy suggestion queue check started")

    result = build_taxonomy_suggestions(
        skills=[
            "JavaScript",
            "ReactJS",
            "Vector Database",
            "RAG Pipeline",
            "Agentic Workflow",
            "Vector Database",
        ],
        job_titles=[
            "SRE",
            "Prompt Engineer",
            "AI Workflow Architect",
            "Prompt Engineer",
        ],
        source_context="step-014-test",
    )

    require(
        result.get("result_version") == "hermes_taxonomy_suggestion_queue_v1",
        "wrong suggestion queue result_version",
    )

    suggestions = result.get("suggestions", [])
    require(isinstance(suggestions, list), "suggestions is not a list")

    observed = {
        (str(item["suggestion_type"]), str(item["observed_term"]))
        for item in suggestions
    }

    require(("skill", "Vector Database") in observed, "Vector Database skill suggestion missing")
    require(("skill", "RAG Pipeline") in observed, "RAG Pipeline skill suggestion missing")
    require(("skill", "Agentic Workflow") in observed, "Agentic Workflow skill suggestion missing")
    require(("job_title", "Prompt Engineer") in observed, "Prompt Engineer job title suggestion missing")
    require(("job_title", "AI Workflow Architect") in observed, "AI Workflow Architect job title suggestion missing")

    require(("skill", "JavaScript") not in observed, "known JavaScript skill should not become a suggestion")
    require(("skill", "ReactJS") not in observed, "known ReactJS alias should not become a suggestion")
    require(("job_title", "SRE") not in observed, "known SRE title alias should not become a suggestion")

    require(result.get("accepted_count") == 0, "accepted_count must remain 0")
    require(result.get("review_required_count") == len(suggestions), "review_required_count mismatch")

    for suggestion in suggestions:
        require(suggestion["status"] == "review_required", "suggestion was not marked review_required")
        require(suggestion["confidence"] == "low", "suggestion confidence should be low")
        require(suggestion["source_context"] == "step-014-test", "source_context was not preserved")

    print("OK: unknown skills create review-required suggestions")
    print("OK: unknown job titles create review-required suggestions")
    print("OK: known skills and aliases are not suggested")
    print("OK: no suggestion is auto-approved")
    print("HERMES-400 taxonomy suggestion queue check PASSED")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"HERMES-400 taxonomy suggestion queue check FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
