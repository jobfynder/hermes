"""Skill Intelligence: canonical identity, classification, relationships, unknown terms and cache versioning.

Runs under the same unittest runner as the rest of the CI suite.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.skill_intelligence import service
from app.skill_intelligence.service import (
    extract_requirement_intelligence,
    get_skill,
    resolve,
    resolve_batch,
    search,
    taxonomy_revision,
)


def _names(result: dict, context: str) -> set[str]:
    return {row["canonical_name"] for row in result["skills"][context]}


class ResolveTests(unittest.TestCase):
    def test_aliases_resolve_to_canonical_identity(self):
        cases = {
            "K8s": "Kubernetes",
            "Postgres": "PostgreSQL",
            "ReactJS": "React",
            "SpringBoot": "Spring Boot",
        }
        for alias, expected in cases.items():
            with self.subTest(alias=alias):
                result = resolve(alias)
                self.assertTrue(result["matched"])
                self.assertEqual(result["canonical_name"], expected)
                self.assertTrue(result["skill_id"].startswith("skill_"))

    def test_alias_and_canonical_name_share_one_identity(self):
        self.assertEqual(resolve("K8s")["skill_id"], resolve("Kubernetes")["skill_id"])

    def test_short_ambiguous_term_is_not_fuzzy_matched(self):
        result = resolve("goe")
        self.assertFalse(result["matched"])
        self.assertEqual(result["match_type"], "unknown")

    def test_batch_and_search_contracts_are_compact_and_stable(self):
        batch = resolve_batch(["K8s", "K8s", "Postgres"])
        self.assertEqual(len(batch["results"]), 2)
        self.assertEqual([row["input"] for row in batch["results"]], ["K8s", "Postgres"])
        results = search("kuber")
        self.assertEqual(results[0]["canonical_name"], "Kubernetes")
        self.assertIn("taxonomy_version", results[0])


class ClassificationTests(unittest.TestCase):
    def test_requirement_classification_and_stack_are_deterministic(self):
        text = "Must have Java, Spring Boot and AWS. Kubernetes preferred. Kafka nice to have."
        result = extract_requirement_intelligence(text)
        self.assertLessEqual({"Java", "Spring Boot", "AWS"}, _names(result, "required"))
        self.assertLessEqual({"Kubernetes", "Kafka"}, _names(result, "preferred"))
        self.assertTrue(result["taxonomy_version"].startswith("skills-"))
        self.assertEqual(list(result["stack"]), sorted(result["stack"]))
        self.assertEqual(result, extract_requirement_intelligence(text))

    def test_required_cue_words(self):
        for cue in ("Must have", "Required", "Mandatory"):
            with self.subTest(cue=cue):
                result = extract_requirement_intelligence(f"{cue}: Java and Docker.")
                self.assertLessEqual({"Java", "Docker"}, _names(result, "required"))
                self.assertFalse(_names(result, "preferred") & {"Java", "Docker"})

    def test_preferred_cue_words(self):
        for phrase in ("Kubernetes preferred.", "Kubernetes is a nice to have.", "Kubernetes is a plus.", "Kubernetes is a bonus."):
            with self.subTest(phrase=phrase):
                result = extract_requirement_intelligence(f"Must have Java. {phrase}")
                self.assertIn("Kubernetes", _names(result, "preferred"))
                self.assertNotIn("Kubernetes", _names(result, "required"))

    def test_a_skill_is_never_listed_twice(self):
        result = extract_requirement_intelligence("Must have Java. Java is also mentioned again here.")
        ids = [row["skill_id"] for group in result["skills"].values() for row in group]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_recognized_skill_carries_identity_and_confidence(self):
        result = extract_requirement_intelligence("Must have Java and K8s.")
        for group in result["skills"].values():
            for row in group:
                self.assertTrue(row["skill_id"].startswith("skill_"))
                self.assertTrue(row["canonical_name"])
                self.assertTrue(row["matched_term"])
                self.assertGreater(row["confidence"], 0)


class RelationshipTests(unittest.TestCase):
    def test_relationship_is_context_not_equivalence(self):
        resolved = resolve("K8s")
        card = get_skill(resolved["skill_id"])
        self.assertIsNotNone(card)
        self.assertTrue(any(row["name"] == "Docker" for row in card["relationships"]))
        self.assertNotEqual(resolve("Docker")["skill_id"], resolved["skill_id"])

    def test_a_related_skill_is_not_counted_as_a_required_match(self):
        result = extract_requirement_intelligence("Must have Kubernetes.")
        self.assertIn("Kubernetes", _names(result, "required"))
        self.assertNotIn("Docker", _names(result, "required"))


class UnknownTermTests(unittest.TestCase):
    TEXT = "Required Skills: Java, Zorblaxian Framework\nPreferred Skills: Kubernetes"

    def test_unknown_terms_are_empty_unless_asked_for(self):
        self.assertEqual(extract_requirement_intelligence(self.TEXT)["unknown_terms"], [])

    def test_unknown_terms_are_returned_when_asked_and_never_include_known_skills(self):
        terms = extract_requirement_intelligence(self.TEXT, include_unknown_terms=True)["unknown_terms"]
        self.assertIn("Zorblaxian Framework", terms)
        self.assertNotIn("Java", terms)
        self.assertNotIn("Kubernetes", terms)

    def test_returning_unknown_terms_never_writes_to_the_learning_queue(self):
        with mock.patch("app.understanding.taxonomy.candidates.cursor", side_effect=AssertionError("database touched")):
            extract_requirement_intelligence(self.TEXT, include_unknown_terms=True)

    def test_unknown_terms_are_capped(self):
        many = "Required Skills: " + ", ".join(f"Zorblax{chr(65 + i)}{chr(65 + j)} Engine" for i in range(6) for j in range(6))
        terms = extract_requirement_intelligence(many, include_unknown_terms=True)["unknown_terms"]
        self.assertLessEqual(len(terms), 20)


class TaxonomyVersionTests(unittest.TestCase):
    def setUp(self):
        service._taxonomy_revision_for_cache.cache_clear()
        self.addCleanup(service._taxonomy_revision_for_cache.cache_clear)

    def test_revision_is_stable_for_unchanged_content(self):
        self.assertEqual(taxonomy_revision(), taxonomy_revision())

    def test_revision_changes_when_the_taxonomy_changes_and_cards_follow(self):
        before = taxonomy_revision()
        entries = service.get_canonical_skill_entries()
        changed = [dict(entry) for entry in entries]
        changed[0]["short_definition"] = "A definition that was edited after the first revision was cached."
        with mock.patch.object(service, "get_canonical_skill_entries", return_value=changed), mock.patch.object(
            service, "get_taxonomy_cache_revision", return_value=(("canonical_skills.json", 1, 1),)
        ):
            after = taxonomy_revision()
            self.assertNotEqual(before, after)
            self.assertEqual(service.skill_card(changed[0])["taxonomy_version"], after)


if __name__ == "__main__":
    unittest.main()
