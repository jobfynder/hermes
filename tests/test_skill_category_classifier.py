from unittest.mock import patch

from app.understanding.taxonomy.skill_category_classifier import (
    classify_skill_category,
    classify_skill_category_deterministically,
)


def test_common_skill_categories_are_deterministic():
    assert classify_skill_category_deterministically("Agentic AI orchestration") == "AI"
    assert classify_skill_category_deterministically("Cloud security platform") == "Cloud"
    assert classify_skill_category_deterministically("CI/CD observability") == "DevOps"


def test_llm_is_only_used_when_rules_cannot_classify():
    with patch(
        "app.understanding.taxonomy.skill_category_classifier.run_llm_fallback",
        return_value={"used": True, "extracted": {"category": "Integration"}},
    ) as llm:
        assert classify_skill_category("Mysterious Runtime", ["Integration", "AI"]) == ("Integration", "llm")
        llm.assert_called_once()


def test_invalid_or_unavailable_llm_output_fails_closed_to_generic_category():
    with patch(
        "app.understanding.taxonomy.skill_category_classifier.run_llm_fallback",
        return_value={"used": False, "reason": "disabled"},
    ):
        assert classify_skill_category("Novel Product", ["AI"]) == ("Tool/Technology", "fallback")
