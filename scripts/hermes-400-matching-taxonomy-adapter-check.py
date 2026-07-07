#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.matching.adapters import build_resume_to_job_request_from_understanding
from app.matching.scorer import evaluate_resume_to_job


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    print("HERMES-400 matching taxonomy adapter check started")

    resume_result = {
        "structured_data": {
            "skills": ["JS", "ReactJS", "K8s"],
            "normalized_skills": ["JavaScript", "React", "Kubernetes"],
            "years_experience": 8,
            "work_authorization": "H1B",
            "location": "Remote",
        }
    }

    job_result = {
        "structured_data": {
            "skills": ["JavaScript", "React", "Kubernetes"],
            "required_skills": ["JS", "ReactJS", "K8s"],
            "preferred_skills": ["AWS"],
            "normalized_skills": ["JavaScript", "React", "Kubernetes"],
            "years_experience": 5,
            "work_authorization": "H1B",
            "location": "Remote",
        }
    }

    request = build_resume_to_job_request_from_understanding(
        resume_result=resume_result,
        job_result=job_result,
    )

    require(request.resume.skills == ["JavaScript", "React", "Kubernetes"], "resume did not prefer normalized_skills")
    require(request.job.skills == ["JavaScript", "React", "Kubernetes"], "job did not prefer normalized_skills")
    require(request.job.required_skills == ["JavaScript", "React", "Kubernetes"], "required_skills were not taxonomy-normalized")
    require(request.job.preferred_skills == ["AWS"], "preferred_skills were not preserved/normalized")

    result = evaluate_resume_to_job(request)

    require(result.score_breakdown.required_skill_score == 100.0, f"expected 100 required skill score, got {result.score_breakdown.required_skill_score}")
    require(result.match_score >= 85, f"expected taxonomy-aware submit score, got {result.match_score}")
    require(result.decision == "submit", f"expected submit decision, got {result.decision}")

    fallback_resume = {
        "structured_data": {
            "skills": ["python3", "fast api"],
        }
    }

    fallback_job = {
        "structured_data": {
            "skills": ["Python", "FastAPI"],
        }
    }

    fallback_request = build_resume_to_job_request_from_understanding(
        resume_result=fallback_resume,
        job_result=fallback_job,
    )

    require(fallback_request.resume.skills == ["Python", "FastAPI"], "fallback resume skills failed")
    require(fallback_request.job.skills == ["Python", "FastAPI"], "fallback job skills failed")
    require(fallback_request.job.required_skills == ["Python", "FastAPI"], "fallback required skills failed")

    print("OK: matching adapter prefers normalized taxonomy skills when available")
    print("OK: matching adapter normalizes required_skills and preferred_skills")
    print("OK: matching adapter remains backward-compatible with existing skills")
    print("HERMES-400 matching taxonomy adapter check PASSED")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"HERMES-400 matching taxonomy adapter check FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
