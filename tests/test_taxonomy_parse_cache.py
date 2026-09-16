import unittest
from unittest.mock import patch
from app.understanding import service
from app.understanding.models import RawDocument

class TaxonomyParseCacheTests(unittest.TestCase):
    def test_taxonomy_change_invalidates_parse(self):
        cache={}
        def save(key,value,_ttl):cache[key]=value
        doc=RawDocument(content='Job Title: Data Engineer\nRequired Skills: SQL',document_kind='job_description',content_type='text/plain')
        with patch.object(service,'cache_get',side_effect=cache.get),patch.object(service,'cache_set',side_effect=save),patch.object(service,'get_taxonomy_cache_revision',return_value=('v1',)) as revision,patch.object(service,'parse_basic_structured_data',wraps=service.parse_basic_structured_data) as parser:
            service.understand_document(doc,skip_llm_fallback=True)
            service.understand_document(doc,skip_llm_fallback=True)
            self.assertEqual(parser.call_count,1)
            revision.return_value=('v2',)
            service.understand_document(doc,skip_llm_fallback=True)
            self.assertEqual(parser.call_count,2)
