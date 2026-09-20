"""The reviewed glossary enrichment and the backfill script that applies it."""

from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

from app.skill_intelligence.enrichment import ENRICHMENT, GENERIC_CATEGORIES, RELATIONSHIP_TYPES

ROOT = Path(__file__).resolve().parents[1]


def _load_backfill():
    spec = importlib.util.spec_from_file_location("skill_backfill", ROOT / "scripts" / "hermes-skill-intelligence-backfill.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EnrichmentContentTests(unittest.TestCase):
    def test_every_entry_is_complete_and_concise(self):
        for name, row in ENRICHMENT.items():
            with self.subTest(skill=name):
                self.assertTrue(row["subcategory"])
                self.assertTrue(12 <= len(row["short_definition"]) <= 220, row["short_definition"])
                self.assertTrue(12 <= len(row["recruiter_explanation"]) <= 280, row["recruiter_explanation"])
                self.assertTrue(row["related_roles"])
                self.assertTrue(row["short_definition"].endswith("."))
                self.assertTrue(row["recruiter_explanation"].endswith("."))

    def test_relationships_use_the_controlled_vocabulary_and_known_targets(self):
        for name, row in ENRICHMENT.items():
            for relation in row.get("relationships", []):
                with self.subTest(skill=name, relation=relation):
                    self.assertIn(relation["type"], RELATIONSHIP_TYPES)
                    self.assertNotEqual(relation["skill"], name)
                    self.assertIn(relation["skill"], ENRICHMENT)

    def test_a_category_override_is_never_generic(self):
        for name, row in ENRICHMENT.items():
            if "category" in row:
                self.assertNotIn(row["category"], GENERIC_CATEGORIES, name)

    def test_no_two_entries_differ_only_by_case(self):
        keys = [name.casefold() for name in ENRICHMENT]
        self.assertEqual(len(keys), len(set(keys)))


class BackfillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backfill = _load_backfill()

    def _data(self):
        return {
            "skills": [
                {"name": "Kubernetes", "category": "DevOps"},
                {"name": "Splunk", "category": "Tool/Technology", "description": "Log tool."},
                {"name": "Docker", "category": "DevOps", "short_definition": "Human written."},
                {"name": "Unrelated Tool", "category": "Tool/Technology"},
            ]
        }

    def test_adds_stable_ids_and_enrichment(self):
        data = self._data()
        counts = self.backfill.apply_enrichment(data)
        by_name = {skill["name"]: skill for skill in data["skills"]}
        self.assertTrue(by_name["Kubernetes"]["skill_id"].startswith("skill_"))
        self.assertTrue(by_name["Kubernetes"]["short_definition"])
        self.assertEqual(counts["ids_added"], 4)

    def test_human_authored_values_win(self):
        data = self._data()
        self.backfill.apply_enrichment(data)
        self.assertEqual({s["name"]: s for s in data["skills"]}["Docker"]["short_definition"], "Human written.")

    def test_only_a_generic_category_is_replaced(self):
        data = self._data()
        counts = self.backfill.apply_enrichment(data)
        by_name = {skill["name"]: skill for skill in data["skills"]}
        self.assertEqual(by_name["Splunk"]["category"], "DevOps")
        self.assertEqual(by_name["Kubernetes"]["category"], "DevOps")
        self.assertEqual(by_name["Unrelated Tool"]["category"], "Tool/Technology")
        self.assertEqual(counts["categories_fixed"], 1)

    def test_running_twice_changes_nothing(self):
        data = self._data()
        self.backfill.apply_enrichment(data)
        first = copy.deepcopy(data)
        counts = self.backfill.apply_enrichment(data)
        self.assertEqual(data, first)
        self.assertEqual(counts["ids_added"], 0)
        self.assertEqual(counts["enriched"], 0)

    def test_names_match_ignoring_case(self):
        data = {"skills": [{"name": "JIRA", "category": "Tool/Technology"}]}
        counts = self.backfill.apply_enrichment(data)
        self.assertEqual(data["skills"][0]["category"], "Project Management")
        self.assertTrue(data["skills"][0]["short_definition"])
        self.assertEqual(counts["enriched"], 1)

    def test_existing_ids_are_never_replaced(self):
        data = {"skills": [{"name": "Kubernetes", "skill_id": "skill_custom", "category": "DevOps"}]}
        self.backfill.apply_enrichment(data)
        self.assertEqual(data["skills"][0]["skill_id"], "skill_custom")


if __name__ == "__main__":
    unittest.main()
