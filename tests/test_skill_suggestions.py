from unittest.mock import patch

from app.skill_intelligence.models import SkillSuggestionRequest
from app.skill_intelligence.suggestions import submit_skill_suggestion


def test_new_skill_uses_review_queue_and_never_approves():
    with patch(
        "app.skill_intelligence.suggestions.queue_user_skill_candidate",
        return_value={
            "outcome": "queued",
            "candidate_id": 12,
            "status": "pending",
            "occurrence_count": 2,
        },
    ) as queue:
        result = submit_skill_suggestion(
            suggestion_type="new_skill",
            term="Emerging Platform",
            skill_id=None,
            requested_fields=[],
            notes=None,
            source_domain="jobs.example.com",
            request_ref="request-1",
        )
    queue.assert_called_once_with(
        "Emerging Platform", request_ref="request-1", source_domain="jobs.example.com"
    )
    assert result["status"] == "pending"
    assert result["outcome"] == "queued"


def test_request_model_bounds_governed_enrichment_fields():
    request = SkillSuggestionRequest(
        suggestion_type="enrichment",
        skill_id="skill_0123456789abcdef0123456789abcdef",
        requested_fields=["recruiter_explanation", "relationships"],
    )
    assert request.requested_fields == ["recruiter_explanation", "relationships"]
