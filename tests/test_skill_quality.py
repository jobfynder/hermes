import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch
from app.understanding.taxonomy.skill_quality import skill_noise_reason
from app.understanding.taxonomy.loader import add_canonical_skill
from app.understanding.parsers.skills import fuzzy_match_terms

class SkillQualityTests(unittest.TestCase):
    def test_noise(self):
        for term in ['receive','Overall','Employment Type','or Microsoft Copilot','Experience with SQL','PEFT (LoRA','alex@example.com']:
            self.assertIsNotNone(skill_noise_reason(term),term)

    def test_real_tools_are_preserved(self):
        for term in ['Go','Rust','Chef','Puppet','Make','BASIC','Ruby on Rails','Qlik Sense','Infrastructure as Code','Adobe Experience Manager','Advanced SQL','Microsoft Copilot','ASP.NET Core']:
            self.assertIsNone(skill_noise_reason(term),term)

    def test_technical_only_policy(self):
        for term in ['Stakeholder Management','Technical Writing','Teamwork','Excellent Communication','Leadership Coaching','time management','structured problem solving']:
            self.assertEqual(skill_noise_reason(term),'nontechnical_professional_skill')
        for term in ['Communication Protocols','Unified Communications','Wireless Communication','Telecommunications','Microsoft Teams','Miro collaboration tools','analytical queries']:
            self.assertIsNone(skill_noise_reason(term),term)

    def test_invalid_addition_does_not_access_database(self):
        with patch('app.understanding.taxonomy.loader.cursor') as db:
            with self.assertRaises(ValueError):add_canonical_skill('Overall')
            db.assert_not_called()

    def test_learned_skills_need_exact_evidence(self):
        self.assertEqual(fuzzy_match_terms({'name':'Some Learned Tool','source':'taxonomy_candidate_approved'}),[])
        self.assertIn('Kubernetes',fuzzy_match_terms({'name':'Kubernetes','source':'curated'}))

    def test_daily_skill_triage_does_not_call_model(self):
        spec=importlib.util.spec_from_file_location('triage_test',Path('scripts/hermes-900-daily-taxonomy-triage.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.object(module,'classify_batch') as llm,patch.object(module,'list_taxonomy_candidates') as listing:
            result=module.triage('skill','ignored')
            self.assertEqual(result['approved'],0)
            llm.assert_not_called();listing.assert_not_called()
