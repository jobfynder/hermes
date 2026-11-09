"""Second-tier taxonomy triage rules (pure functions)."""
import unittest

from app.understanding.taxonomy.triage_rules import APPROVE, REJECT, REVIEW, boilerplate_decision, skill_decision


class SkillRules(unittest.TestCase):
    def test_rejects_non_skills_with_a_reason(self):
        for term in ("issue fixing", "high-quality delivery", "o Claims", "Key Must-Have Skills",
                     "Independent visa candidates only", "Senior Data Analyst", "robots.txt",
                     "Governance: SOX controls", "Tier 1", "s10061992", "regulated enterprise environment",
                     "Release and delivery governance", "widgets"):
            decision, reason = skill_decision(term)
            self.assertEqual(decision, REJECT, term)
            self.assertTrue(reason)

    def test_approves_only_distinctive_product_names(self):
        for term in ("AirWatch", "RevPro", "DataWeave 2.x", "Auth0", "pg_restore", "Cursor IDE"):
            self.assertEqual(skill_decision(term)[0], APPROVE, term)

    def test_ambiguous_capitalised_names_go_to_a_human(self):
        for term in ("Certinia", "Metronome", "Transit", "Deal Desk"):
            self.assertEqual(skill_decision(term)[0], REVIEW, term)

    def test_catalogued_terms_are_trusted(self):
        self.assertEqual(skill_decision("issue fixing", catalogued=True)[0], APPROVE)


class BoilerplateRules(unittest.TestCase):
    def test_repeated_requirement_lines_are_job_content_not_boilerplate(self):
        for line in ("Collaborate with internal business partners and external vendors",
                     "* Strong communication, facilitation, and stakeholder management skills.",
                     "o            Regulatory and audit requirements",
                     "Deep knowledge in Databricks & AWS eco-systems",
                     "Interview Process (Is face to face required?)"):
            decision, reason = boilerplate_decision(line)
            self.assertEqual(decision, REJECT, line)
            self.assertIn("job", reason.lower())

    def test_footer_shaped_lines_are_never_auto_rejected(self):
        for line in ("To unsubscribe reply with REMOVE in the subject line",
                     "This email and any attachments are confidential",
                     "All rights reserved. Copyright Acme Staffing"):
            self.assertEqual(boilerplate_decision(line)[0], REVIEW, line)

    def test_tiny_generic_lines_are_rejected(self):
        self.assertEqual(boilerplate_decision("Thank you")[0], REJECT)


if __name__ == "__main__":
    unittest.main()
