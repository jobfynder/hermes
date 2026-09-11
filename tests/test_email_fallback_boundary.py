import unittest
from unittest.mock import patch,Mock
from app.understanding.models import RawDocument
from app.understanding import service
from app.email_parsing import parsers

class EmailFallbackBoundaryTests(unittest.TestCase):
    def test_deterministic_requirement_parser_skips_llm(self):
        with patch.object(parsers,'understand_document',wraps=service.understand_document) as understand:
            parsers.parse_requirement_email('Job Title: Data Engineer\nCompany: Example\nRequired Skills: SQL')
            self.assertTrue(understand.call_args.kwargs['skip_llm_fallback'])

    def test_successful_fallback_preserves_raw_text(self):
        text='A fictional role with SQL and Python experience required.'
        fallback=Mock(should_call_llm=True);fallback.model_dump.return_value={}
        with patch.object(service,'cache_get',return_value=None),patch.object(service,'cache_set'),patch.object(service,'decide_fallback',return_value=fallback),patch.object(service,'apply_llm_fallback',return_value={'used':True,'extracted':{'job_title':'Data Engineer'}}):
            result=service.understand_document(RawDocument(content=text,content_type='text/plain',document_kind='job_description'))
            self.assertEqual(result.extracted_text.text,text)
            self.assertEqual(result.structured_data['llm_fallback_extracted']['job_title'],'Data Engineer')
