import unittest
from unittest.mock import patch
from app.understanding.taxonomy import descriptions,title_family_classifier

class DeterministicTaxonomyTests(unittest.TestCase):
    def test_descriptions_do_not_call_llm_automatically(self):
        with patch.object(descriptions,'litellm_configured',return_value=True),patch.object(descriptions,'_call_litellm_with_model') as model:
            self.assertIsNone(descriptions.generate_skill_description('Unlisted Example Technology'))
            self.assertIsNotNone(descriptions.generate_skill_description('Python'))
            model.assert_not_called()

    def test_family_classification_does_not_call_llm_automatically(self):
        with patch.object(title_family_classifier,'litellm_configured',return_value=True),patch.object(title_family_classifier,'_call_litellm_with_model') as model:
            self.assertEqual(title_family_classifier.classify_job_title_family('Unlisted Example Position',[]),('Unclassified','none'))
            model.assert_not_called()
