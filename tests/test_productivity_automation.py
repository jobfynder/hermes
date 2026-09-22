import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _load_triage():
    spec = importlib.util.spec_from_file_location(
        "daily_taxonomy_triage", ROOT / "scripts" / "hermes-900-daily-taxonomy-triage.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class ProductivityAutomationTests(unittest.TestCase):
    def test_deterministic_boilerplate_only_approves_high_precision_patterns(self):
        module = _load_triage()
        self.assertEqual(module.deterministic_boilerplate_decision("Required Qualifications:"), "approve")
        self.assertEqual(module.deterministic_boilerplate_decision("Click here to unsubscribe"), "approve")
        self.assertEqual(module.deterministic_boilerplate_decision("5 years of Snowflake migration experience"), "reject")
        self.assertEqual(module.deterministic_boilerplate_decision("Customer-focused mindset"), "review")

    def test_missing_descriptions_remain_retryable_when_llm_is_unavailable(self):
        module = _load_triage()
        entries = [{"name": "AWS", "category": "Cloud"}, {"name": "Long Tail Tool", "category": "Tool/Technology"}]
        with (
            patch.object(module, "get_canonical_skill_entries", return_value=entries),
            patch.object(module, "generate_skill_description", side_effect=["Cloud definition", None]),
            patch.object(module, "set_skill_description", return_value=True) as write,
            patch.object(module, "litellm_configured", return_value=False),
            patch.dict(module.os.environ, {"HERMES_SKILL_DESCRIPTION_LLM_FALLBACK_ENABLED": "true"}),
        ):
            result = module.backfill_missing_descriptions()
        self.assertEqual(result["deterministic_filled"], 1)
        self.assertEqual(result["remaining"], 1)
        self.assertFalse(result["llm_enabled"])
        write.assert_called_once()
