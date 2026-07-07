import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.jobfynder import build_submission_request_from_jobfynder_event
from app.integrations.models import IntegrationEnvelope, IntegrationSource
from app.submission_intelligence.service import evaluate_submission_intelligence


def test_submission_handoff_adapter():
    envelope = IntegrationEnvelope(
        event_type="workflow_handoff",
        source=IntegrationSource(
            provider="jobfynder_api",
            external_id="jobfynder-submission-001",
            channel="api",
            actor_id="recruiter-001",
        ),
        correlation_id="corr-jobfynder-001",
        payload={
            "submission_id": "submission-001",
            "current_stage": "discovered",
            "requirement": {
                "job_id": "job-001",
                "title": "Python Developer",
                "client": "Acme",
                "required_skills": ["Python", "FastAPI"],
                "preferred_skills": ["PostgreSQL"],
                "work_authorization": "H1B",
            },
            "consultant": {
                "consultant_id": "consultant-001",
                "name": "Test Consultant",
                "skills": ["Python", "FastAPI", "PostgreSQL"],
                "years_experience": 7,
                "work_authorization": "H1B",
            },
            "relationship": {
                "recruiter": {
                    "party_id": "recruiter-001",
                    "name": "Test Recruiter",
                    "role": "recruiter",
                    "company": "Acme Staffing",
                },
                "trust_level": "known",
            },
            "match_result": {
                "decision": "submit",
                "match_score": 91,
            },
            "taxonomy_context": {
                "normalized_skills": ["Python", "FastAPI", "PostgreSQL"],
            },
        },
    )

    request = build_submission_request_from_jobfynder_event(envelope)
    result = evaluate_submission_intelligence(request)

    assert request.submission_id == "submission-001"
    assert request.requirement.job_id == "job-001"
    assert request.consultant.consultant_id == "consultant-001"
    assert result.recommended_stage == "matched"
    assert result.stage_changed is True


def test_duplicate_handoff_adapter():
    envelope = IntegrationEnvelope(
        event_type="workflow_handoff",
        source=IntegrationSource(provider="jobfynder_api"),
        payload={
            "current_stage": "matched",
            "requirement": {"job_id": "job-001"},
            "consultant": {"consultant_id": "consultant-001"},
            "match_result": {"decision": "submit", "match_score": 92},
            "existing_submission_keys": ["consultant-001:job-001"],
        },
    )

    request = build_submission_request_from_jobfynder_event(envelope)
    result = evaluate_submission_intelligence(request)

    assert result.recommended_stage == "duplicate_risk"
    assert result.conflicts


if __name__ == "__main__":
    test_submission_handoff_adapter()
    test_duplicate_handoff_adapter()
    print("HERMES-600 Jobfynder adapter checks passed.")
