import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from app.understanding.taxonomy.title_family_classifier import classify_family_deterministically


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
    def test_job_title_family_rules_cover_production_title_shapes(self):
        cases = {
            "Oracle WMS Functional Consultant": "ERP",
            "Senior Network Security Analyst": "Cybersecurity",
            "Snowflake Platform Administrator": "Data",
            "Microsoft 365 Exchange Online Administrator": "Infrastructure",
            "Workday Payroll Integration Lead": "HCM",
            "Mainframe Tester": "Quality Engineering",
            "Senior Java Technical Lead": "Software Engineering",
            "Epic Deployment Analyst": "Healthcare Management",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(classify_family_deterministically(title), expected)

    def test_ambiguous_or_non_title_values_are_not_force_classified(self):
        for title in ("Remote", "Available Consultant", "Manager", "Hello", "Looking for Construction Manager"):
            with self.subTest(title=title):
                self.assertIsNone(classify_family_deterministically(title))

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
