from contextlib import contextmanager
from datetime import UTC, datetime
import json
from unittest.mock import MagicMock, patch

import pytest

from app.skill_intelligence.models import SkillSuggestionRequest
from app.skill_intelligence.suggestions import (
    _deterministic_enrichment_proposal,
    _clean_proposal,
    generate_enrichment_proposal,
    review_enrichment_request,
    submit_skill_suggestion,
)
from app.understanding.taxonomy.identity import stable_skill_id
from app.understanding.taxonomy.loader import apply_canonical_skill_enrichment


@contextmanager
def _cursor_context(value):
    yield value


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


def test_enrichment_does_not_queue_fields_that_are_already_populated():
    card = {
        "canonical_name": "AWS",
        "definition": "Cloud platform.",
        "aliases": ["Amazon Web Services"],
    }
    with patch("app.skill_intelligence.suggestions.get_skill", return_value=card), patch(
        "app.skill_intelligence.suggestions.cursor"
    ) as db:
        result = submit_skill_suggestion(
            suggestion_type="enrichment",
            term=None,
            skill_id="skill_0123456789abcdef0123456789abcdef",
            requested_fields=["definition", "aliases"],
            notes=None,
            source_domain=None,
            request_ref="same-request",
        )
    assert result["outcome"] == "already_reviewed"
    db.assert_not_called()


def test_duplicate_request_reference_does_not_increment_enrichment_evidence():
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"id": 7, "requested_fields": ["definition"], "request_refs": ["same-request"]},
        None,
        {"id": 7, "occurrence_count": 3, "status": "pending"},
    ]
    with patch(
        "app.skill_intelligence.suggestions.get_skill",
        return_value={"canonical_name": "Sparse Tool", "definition": None},
    ), patch("app.skill_intelligence.suggestions.cursor", return_value=_cursor_context(cur)):
        result = submit_skill_suggestion(
            suggestion_type="enrichment",
            term=None,
            skill_id="skill_0123456789abcdef0123456789abcdef",
            requested_fields=["definition"],
            notes=None,
            source_domain="jobs.example.com",
            request_ref="same-request",
        )
    update_call = next(call for call in cur.execute.call_args_list if call.args[0].startswith("UPDATE taxonomy_enrichment_requests"))
    assert update_call.args[1][4] == 0
    assert result["candidate_id"] == 7


def test_ready_proposal_is_reused_without_another_llm_call():
    generated_at = datetime.now(UTC)
    pending = {
        "id": 7,
        "skill_id": "skill_0123456789abcdef0123456789abcdef",
        "canonical_name": "AWS",
        "requested_fields": ["definition"],
        "notes": None,
        "proposal": {"definition": "Cloud platform."},
        "proposal_status": "ready",
        "proposal_prompt_id": "jf.taxonomy.skill-enrichment.propose",
        "proposal_run_id": "run-1",
        "proposal_model": "model",
        "proposal_generated_at": generated_at,
        "proposal_error": None,
    }
    cur = MagicMock()
    cur.fetchone.return_value = pending
    with patch("app.skill_intelligence.suggestions.cursor", return_value=_cursor_context(cur)), patch(
        "app.skill_intelligence.suggestions.run_llm_fallback"
    ) as llm:
        result = generate_enrichment_proposal(7)
    assert result["proposal_status"] == "ready"
    assert result["proposal_generated_at"] == generated_at.isoformat()
    llm.assert_not_called()


def test_human_approval_applies_exact_reviewed_proposal():
    proposal = {
        "definition": "A reviewed definition.",
        "recruiter_explanation": None,
        "aliases": [],
        "relationships": [],
        "related_roles": [],
    }
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {
            "skill_id": "skill_0123456789abcdef0123456789abcdef",
            "requested_fields": ["definition"],
            "proposal": proposal,
        },
        {"id": 7, "skill_id": "skill_0123456789abcdef0123456789abcdef", "canonical_name": "AWS", "status": "approved"},
    ]
    with patch("app.skill_intelligence.suggestions.cursor", return_value=_cursor_context(cur)), patch(
        "app.skill_intelligence.suggestions.get_skill",
        return_value={"canonical_name": "AWS", "definition": None},
    ), patch(
        "app.skill_intelligence.suggestions.apply_canonical_skill_enrichment",
        return_value={"updated": True, "applied_fields": ["definition"]},
    ) as apply:
        result = review_enrichment_request(7, "approved", "reviewer-1")
    apply.assert_called_once_with(
        "skill_0123456789abcdef0123456789abcdef", proposal, "reviewer-1"
    )
    assert result["apply_result"]["applied_fields"] == ["definition"]


def test_proposal_rejects_alias_collisions_and_unknown_relationship_targets():
    base = {
        "definition": None,
        "recruiter_explanation": None,
        "aliases": ["Existing Other Skill"],
        "relationships": [],
        "related_roles": [],
    }
    with patch(
        "app.skill_intelligence.suggestions.resolve",
        return_value={"matched": True, "skill_id": "skill_other", "canonical_name": "Other"},
    ), pytest.raises(ValueError, match="Alias already belongs"):
        _clean_proposal(base, ["aliases"], "skill_current")

    relationship = {**base, "aliases": [], "relationships": [{"type": "builds_on", "skill": "Imaginary"}]}
    with patch(
        "app.skill_intelligence.suggestions.resolve",
        return_value={"matched": False, "skill_id": None, "canonical_name": None},
    ), pytest.raises(ValueError, match="not a canonical skill"):
        _clean_proposal(relationship, ["relationships"], "skill_current")


def test_approved_enrichment_only_fills_missing_fields_and_is_idempotent(tmp_path):
    alpha_id = stable_skill_id("Alpha")
    taxonomy_path = tmp_path / "canonical_skills.json"
    taxonomy_path.write_text(json.dumps({"skills": [
        {"skill_id": alpha_id, "name": "Alpha", "category": "Tools", "skill_type": "tool", "description": "Human definition.", "aliases": []},
        {"skill_id": stable_skill_id("Beta"), "name": "Beta", "category": "Tools", "skill_type": "tool", "aliases": []},
    ]}), encoding="utf-8")
    cur = MagicMock()
    values = {
        "definition": "LLM definition must not replace the human value.",
        "recruiter_explanation": "Reviewed recruiter context.",
        "aliases": ["Alpha Tool", "Alpha Tool"],
        "relationships": [{"type": "builds_on", "skill": "Beta"}],
        "related_roles": ["Platform Engineer", "Platform Engineer"],
    }
    with patch("app.understanding.taxonomy.loader.cursor", side_effect=lambda: _cursor_context(cur)), patch(
        "app.understanding.taxonomy.loader._writable_taxonomy_path", return_value=taxonomy_path
    ), patch("app.understanding.taxonomy.loader.clear_taxonomy_cache"):
        first = apply_canonical_skill_enrichment(alpha_id, values, "reviewer-1")
        second = apply_canonical_skill_enrichment(alpha_id, values, "reviewer-1")
    saved = json.loads(taxonomy_path.read_text(encoding="utf-8"))["skills"][0]
    assert saved["description"] == "Human definition."
    assert set(first["applied_fields"]) == {"recruiter_explanation", "aliases", "relationships", "related_roles"}
    assert second["applied_fields"] == []
    assert saved["aliases"] == ["Alpha Tool"]
    assert saved["relationships"] == [{"type": "builds_on", "skill": "Beta"}]
    assert saved["related_roles"] == ["Platform Engineer"]
    assert saved["field_provenance"]["aliases"]["source"] == "human_approved_enrichment_proposal"


def test_enrichment_uses_deterministic_definition_and_related_roles_before_llm():
    card = {
        "canonical_name": "Python",
        "category": "Programming Language",
        "definition": None,
        "related_roles": [],
        "aliases": ["Python3"],
    }
    with patch(
        "app.skill_intelligence.suggestions.get_job_title_entries",
        return_value=[{"title": "Python Developer"}, {"title": "Java Developer"}],
    ):
        proposal = _deterministic_enrichment_proposal(card, ["definition", "related_roles"])
    assert proposal["definition"]
    assert proposal["related_roles"] == ["Python Developer"]
