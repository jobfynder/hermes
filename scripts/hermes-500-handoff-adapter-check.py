import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.submission_intelligence.adapters import (
    build_submission_intelligence_request_from_handoff,
)
from app.submission_intelligence.models import SubmissionHandoffEvaluationRequest
from app.submission_intelligence.service import evaluate_submission_intelligence


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def sample_resume_understanding_result():
    return {
        "result_version": "hermes_understanding_result_v1",
        "document_kind": "resume",
        "structured_data": {
            "document_kind": "resume",
            "skills": [
                {"name": "Python", "confidence": 1.0, "method": "test"},
                {"name": "FastAPI", "confidence": 1.0, "method": "test"},
                {"name": "PostgreSQL", "confidence": 1.0, "method": "test"},
            ],
            "normalized_skills": ["Python", "FastAPI", "PostgreSQL"],
            "normalized_job_titles": ["Python Developer"],
            "years_experience": 6,
            "location": "Remote",
            "work_authorization": "USC",
            "taxonomy_signals": {
                "skills": [
                    {"raw_text": "Python", "normalized": "Python"},
                    {"raw_text": "FastAPI", "normalized": "FastAPI"},
                ]
            },
        },
        "extracted_text": {
            "text": "Python FastAPI PostgreSQL developer with 6 years experience."
        },
    }


def sample_job_understanding_result():
    return {
        "result_version": "hermes_understanding_result_v1",
        "document_kind": "job_description",
        "structured_data": {
            "document_kind": "job_description",
            "job_title": "Python FastAPI Developer",
            "required_skills": [
                {"name": "Python", "confidence": 1.0, "method": "test"},
                {"name": "FastAPI", "confidence": 1.0, "method": "test"},
                {"name": "PostgreSQL", "confidence": 1.0, "method": "test"},
            ],
            "preferred_skills": [
                {"name": "AWS", "confidence": 1.0, "method": "test"}
            ],
            "normalized_skills": ["Python", "FastAPI", "PostgreSQL", "AWS"],
            "normalized_job_titles": ["Python Developer"],
            "years_experience": 5,
            "location": "Remote",
            "work_authorization": "USC",
            "taxonomy_signals": {
                "skills": [
                    {"raw_text": "Python", "normalized": "Python"},
                    {"raw_text": "AWS", "normalized": "AWS"},
                ]
            },
        },
        "extracted_text": {
            "text": "Need Python FastAPI Developer with PostgreSQL and AWS."
        },
    }


def sample_match_result():
    return {
        "match_score": 88.5,
        "decision": "submit",
        "score_breakdown": {
            "required_skill_score": 100.0,
            "preferred_skill_score": 0.0,
            "years_score": 100.0,
            "work_authorization_score": 100.0,
            "location_score": 100.0,
        },
        "matched_required_skills": ["Python", "FastAPI", "PostgreSQL"],
        "missing_required_skills": [],
        "matched_preferred_skills": [],
        "reasons": ["All required skills are covered"],
        "risks": [],
        "recommendation": "Submit candidate. Core requirements are covered.",
        "matcher_version": "basic_local_matcher_v1",
        "policy_snapshot": {"matcher_version": "basic_local_matcher_v1"},
    }


def run_handoff_adapter_check():
    handoff_request = SubmissionHandoffEvaluationRequest(
        current_stage="discovered",
        resume_result=sample_resume_understanding_result(),
        job_result=sample_job_understanding_result(),
        match_result=sample_match_result(),
        consultant_id="consultant-handoff-001",
        job_id="job-handoff-001",
        resume_id="resume-handoff-001",
    )

    submission_request = build_submission_intelligence_request_from_handoff(handoff_request)

    assert_equal(submission_request.requirement.job_id, "job-handoff-001", "job_id")
    assert_equal(submission_request.requirement.title, "Python FastAPI Developer", "job_title")
    assert_equal(submission_request.consultant.consultant_id, "consultant-handoff-001", "consultant_id")
    assert_equal(submission_request.consultant.resume_id, "resume-handoff-001", "resume_id")
    assert "Python" in submission_request.requirement.required_skills
    assert "FastAPI" in submission_request.consultant.skills
    assert submission_request.taxonomy_context["job_taxonomy_signals"]
    assert_equal(submission_request.match_result["decision"], "submit", "match decision")

    result = evaluate_submission_intelligence(submission_request)

    assert_equal(result.recommended_stage, "matched", "recommended_stage")
    assert_equal(result.stage_changed, True, "stage_changed")
    assert result.follow_up.required is True
    assert result.handoff["job_id"] == "job-handoff-001"
    assert result.handoff["consultant_id"] == "consultant-handoff-001"


def run_handoff_duplicate_check():
    handoff_request = SubmissionHandoffEvaluationRequest(
        current_stage="matched",
        resume_result=sample_resume_understanding_result(),
        job_result=sample_job_understanding_result(),
        match_result=sample_match_result(),
        consultant_id="consultant-handoff-001",
        job_id="job-handoff-001",
        existing_submission_keys=["consultant-handoff-001:job-handoff-001"],
    )

    submission_request = build_submission_intelligence_request_from_handoff(handoff_request)
    result = evaluate_submission_intelligence(submission_request)

    assert_equal(result.recommended_stage, "duplicate_risk", "duplicate recommended_stage")
    assert result.conflicts
    assert result.follow_up.required is True


if __name__ == "__main__":
    run_handoff_adapter_check()
    run_handoff_duplicate_check()
    print("HERMES-500 handoff adapter checks passed.")
