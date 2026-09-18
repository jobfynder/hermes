import os, unittest
from fastapi.testclient import TestClient
from app.main import app
from app.security.rbac import get_current_user

class TaxonomyPaginationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if os.getenv('HERMES_RELIABILITY_TEST_DB')!='1': raise unittest.SkipTest('Synthetic database only')
 def setUp(self): app.dependency_overrides[get_current_user]=lambda:{'permissions':['understanding:read','drafts:publish']}
 def tearDown(self): app.dependency_overrides.pop(get_current_user,None)
 def test_page_is_bounded_and_reports_totals(self):
  with TestClient(app) as client:
   result=client.get('/understanding/taxonomy/skills/page?page_size=10').json()
   self.assertEqual(len(result['items']),10);self.assertGreater(result['total_count'],10)
   self.assertEqual(client.get('/understanding/taxonomy/skills/page?page_size=101').status_code,422)
   self.assertEqual(client.get('/understanding/taxonomy/skills/page?sort=invalid').status_code,422)
 def test_search_and_category_are_server_side(self):
  with TestClient(app) as client:
   result=client.get('/understanding/taxonomy/skills/page?q=python&page_size=10').json()
   self.assertTrue(all('python' in (' '.join([x['name'],*x.get('aliases',[]),x.get('description') or ''])).lower() for x in result['items']))
 def test_oversized_bulk_selection_is_rejected(self):
  with TestClient(app) as client:
   result=client.post('/taxonomy/skills/bulk-delete',json={'names':[f'skill-{i}' for i in range(101)]})
   self.assertEqual(result.status_code,422)
