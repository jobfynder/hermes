import unittest
from unittest.mock import patch
from app.email_parsing.llm_fallback import apply_job_requirement_fallback,apply_hotlist_fallback
class FallbackCompletionTests(unittest.TestCase):
 def test_partial_job_stays_in_review(self):
  parsed={'confidence':0.35,'records':[{'job_title':None,'company':None,'required_skills':[]}]}
  with patch('app.email_parsing.llm_fallback.run_llm_fallback',return_value={'used':True,'extracted':{'location':'Remote'}}) as call:
   result,_=apply_job_requirement_fallback('Incomplete job',parsed)
  self.assertTrue(result['requires_review'])
  self.assertIn('job_title_missing',result['records'][0]['warnings'])
  self.assertEqual(call.call_args.kwargs['cache_ttl_seconds'],86400)
 def test_partial_hotlist_stays_in_review(self):
  with patch('app.email_parsing.llm_fallback.run_llm_fallback',return_value={'used':True,'extracted':{'consultants':[{'candidate_name':'Example'}]}}):
   result,_=apply_hotlist_fallback('Incomplete hotlist',{'confidence':0.2})
  self.assertTrue(result['requires_review'])
 def test_empty_input_never_calls_model(self):
  with patch('app.email_parsing.llm_fallback.run_llm_fallback') as call:
   apply_job_requirement_fallback(' ',{'confidence':0})
   apply_hotlist_fallback('',{'confidence':0})
  call.assert_not_called()
 def test_complete_deterministic_result_never_calls_model(self):
  with patch('app.email_parsing.llm_fallback.run_llm_fallback') as call:
   apply_job_requirement_fallback('Complete job',{'confidence':0.92})
   apply_hotlist_fallback('Complete hotlist',{'confidence':0.92})
  call.assert_not_called()
