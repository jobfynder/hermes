import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.submission_intelligence.models import (
    SubmissionConsultantSnapshot,
    SubmissionIntelligenceRequest,
    SubmissionRequirementSnapshot,
)
from app.submission_intelligence.service import evaluate_submission_intelligence


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def run_match_to_submission_foundation_check():
    request = SubmissionIntelligenceRequest(
        current_stage="discovered",
        requirement=SubmissionRequirementSnapshot(
            job_id="job-123",
            title="Python FastAPI Developer",
            required_skills=["Python", "FastAPI", "PostgreSQL"],
            location="Remote",
            work_authorization="USC",
        ),
        consultant=SubmissionConsultantSnapshot(
            consultant_id="consultant-456",
            name="Sample Consultant",
            skills=["Python", "FastAPI", "PostgreSQL", "AWS"],
            location="Remote",
            work_authorization="USC",
            years_experience=6,
        ),
        match_result={
            "decision": "submit",
            "match_score": 88.5,
        },
        taxonomy_context={
            "normalized_skills": ["Python", "FastAPI", "PostgreSQL"],
        },
    )

    result = evaluate_submission_intelligence(request)

    assert_equal(result.current_stage, "discovered", "current_stage")
    assert_equal(result.recommended_stage, "matched", "recommended_stage")
    assert_equal(result.stage_changed, True, "stage_changed")
    assert result.follow_up.required is True
    assert result.events
    assert result.handoff["job_id"] == "job-123"
    assert result.handoff["consultant_id"] == "consultant-456"


def run_duplicate_risk_check():
    request = SubmissionIntelligenceRequest(
        current_stage="matched",
        requirement=SubmissionRequirementSnapshot(job_id="job-123"),
        consultant=SubmissionConsultantSnapshot(consultant_id="consultant-456"),
        existing_submission_keys=["consultant-456:job-123"],
        match_result={
            "decision": "submit",
            "match_score": 91,
        },
    )

    result = evaluate_submission_intelligence(request)

    assert_equal(result.recommended_stage, "duplicate_risk", "duplicate recommended_stage")
    assert result.conflicts
    assert result.follow_up.required is True
    assert result.follow_up.priority == "high"


if __name__ == "__main__":
    run_match_to_submission_foundation_check()
    run_duplicate_risk_check()
    print("HERMES-500 submission intelligence foundation checks passed.")
