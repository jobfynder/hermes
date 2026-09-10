import json,os,unittest
from uuid import uuid4
from app.runtime.db import cursor,init_schema
from app.drafts.listing import list_draft_page


class DashboardListingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert 'hermes-dashboard-test-db' in os.environ['DATABASE_URL'] or os.getenv('HERMES_RELIABILITY_TEST_DB') == '1'
        init_schema()

    def setUp(self):
        self.ids=[]
        with cursor() as cur:
            for i in range(125):
                draft_id=uuid4(); self.ids.append(draft_id)
                metadata={'sender':{'email':f'sender{i}@example.test'},'private_unused_field':'x'*1000}
                if i>=120: metadata['exact_content_duplicate_of']='canonical-test'
                payload={'structured_data':{'email_parsing':{'records':[{'job_title':'100% Engineer' if i==0 else f'Engineer {i}'}]}}}
                cur.execute("""INSERT INTO drafts(draft_id,draft_type,status,source,title,payload,metadata,created_at)
                    VALUES(%s,'draft_job_requirement',%s,'dashboard_test','Subject',%s,%s,'2026-01-01'::timestamptz + %s * interval '1 second')""",
                    (draft_id,'needs_review' if i<80 else 'draft',json.dumps(payload),json.dumps(metadata),i))

    def tearDown(self):
        with cursor() as cur:
            cur.execute('DELETE FROM drafts WHERE draft_id=ANY(%s)',(self.ids,))

    def test_page_is_bounded_and_stable(self):
        first=list_draft_page(); second=list_draft_page(page=2)
        self.assertEqual((len(first['items']),first['total_count']), (50,120))
        self.assertFalse({r['draft_id'] for r in first['items']} & {r['draft_id'] for r in second['items']})
        self.assertEqual(first['counts']['needsReview'],80)
        self.assertNotIn('private_unused_field',first['items'][0]['metadata'])

    def test_filters_and_duplicates(self):
        self.assertEqual(list_draft_page(status='needs_review')['total_count'],80)
        self.assertEqual(list_draft_page(include_duplicates=True)['total_count'],125)
        self.assertEqual(list_draft_page(draft_type='draft_hotlist')['total_count'],0)

    def test_search_is_literal_and_uses_parsed_title(self):
        result=list_draft_page(search='100%')
        self.assertEqual(result['total_count'],1)
        self.assertEqual(result['items'][0]['display_title'],'100% Engineer')
        self.assertEqual(list_draft_page(search='sender12@example.test')['total_count'],1)

    def test_page_clamps_and_bounds(self):
        self.assertEqual(list_draft_page(page=100)['page'],3)
        with self.assertRaises(ValueError): list_draft_page(page_size=1000)


if __name__=='__main__': unittest.main()
