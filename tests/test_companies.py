import json, os, unittest
from uuid import uuid4
from app.companies.service import extract_company, normalize_company_name, corporate_domain, sync_company_batch, list_companies, get_company
from app.runtime.db import cursor, init_schema

def payload(domain='agency.example', title='Data Engineer'):
    def field(value): return {'value':value,'confidence':0.9,'method':'relay_from_block'}
    return {'structured_data':{'signature':{'contact':{
        'company_name':field('Example Staffing'),'email':field('recruiter@'+domain),
        'full_name':field('Example Recruiter'),'website':field('https://'+domain)}},
        'email_parsing':{'records':[{'record_type':'job_requirement','job_title':title,
        'company':'Different End Client','location':'Austin','job_description':'Build reliable data pipelines with Python and SQL for reporting.',
        'requires_review':False}]}}}

class CompanyExtractionTests(unittest.TestCase):
    def test_company_name_excludes_keywords_and_address_suffix(self):
        self.assertIsNone(normalize_company_name('Keywords: information technology golang Idaho'))
        self.assertEqual(normalize_company_name('Avance Consulting |1170 Rt 22 | Bridgewater'),'Avance Consulting')
        self.assertEqual(normalize_company_name('Example Staffing, 123 Main Street'),'Example Staffing')
        self.assertEqual(normalize_company_name('Delta System & Software Inc.'),'Delta System & Software Inc.')

    def test_signature_company_is_distinct_from_end_client(self):
        result,reason=extract_company({'draft_id':uuid4(),'status':'draft','payload':payload()})
        self.assertEqual(reason,'linked')
        self.assertEqual(result['name'],'Example Staffing')
        self.assertEqual(result['jobs'][0]['named_client'],'Different End Client')
    def test_shared_and_relay_domains_excluded(self):
        for domain in ('gmail.com','jobs.nvoids.com','prohirespowerhouse.com','techmail001.email','groups.google.com'):
            self.assertIsNone(corporate_domain(domain))
            result,_=extract_company({'draft_id':uuid4(),'status':'draft','payload':payload(domain)})
            self.assertIsNone(result)
    def test_duplicate_sources_and_rejected_drafts_excluded(self):
        for row in ({'status':'spam'},{'status':'rejected'},{'metadata':{'exact_content_duplicate_of':'original'}}):
            result,_=extract_company({'draft_id':uuid4(),'payload':payload(),**row})
            self.assertIsNone(result)
    def test_identical_requirements_share_identity_across_sources(self):
        a,_=extract_company({'draft_id':uuid4(),'payload':payload()})
        b,_=extract_company({'draft_id':uuid4(),'payload':payload()})
        self.assertEqual(a['jobs'][0]['key'],b['jobs'][0]['key'])
    def test_company_name_alone_does_not_establish_identity(self):
        source=payload();source['structured_data']['signature']['contact'].pop('email')
        result,reason=extract_company({'draft_id':uuid4(),'payload':source})
        self.assertIsNone(result)
        self.assertEqual(reason,'corporate_signature_email_missing')

class CompanyProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv('HERMES_RELIABILITY_TEST_DB')!='1':raise unittest.SkipTest('Synthetic database only')
        init_schema()
    def setUp(self):
        self.ids=[];self.domain=uuid4().hex+'.example.com'
    def tearDown(self):
        with cursor() as cur:
            cur.execute('DELETE FROM drafts WHERE draft_id=ANY(%s)',(self.ids,))
            cur.execute('DELETE FROM hermes_companies WHERE identity_domain=%s',(self.domain,))
    def add(self):
        draft=uuid4();self.ids.append(draft)
        with cursor() as cur:
            cur.execute("INSERT INTO drafts(draft_id,draft_type,status,source,channel,payload) VALUES (%s,'draft_job_requirement','draft','test','email',%s)",(draft,json.dumps(payload(self.domain))))
        return draft
    def test_reprocessing_is_idempotent_and_jobs_deduplicate(self):
        self.add();self.add()
        sync_company_batch();sync_company_batch()
        result=list_companies(self.domain)
        self.assertEqual(result['total_count'],1)
        company=get_company(result['items'][0]['company_id'])
        self.assertEqual(company['source_count'],2)
        self.assertEqual(company['contact_count'],1)
        self.assertEqual(company['job_requirements'],1)
        self.assertEqual(company['verification_status'],'unverified')
        self.assertEqual(company['claim_status'],'unclaimed')
    def test_corrected_source_replaces_projection(self):
        draft=self.add();sync_company_batch()
        changed=payload(self.domain,'Platform Engineer')
        with cursor() as cur:
            cur.execute('UPDATE drafts SET payload=%s,updated_at=clock_timestamp() WHERE draft_id=%s',(json.dumps(changed),draft))
        sync_company_batch()
        company=get_company(list_companies(self.domain)['items'][0]['company_id'])
        self.assertEqual(company['sources'][0]['jobs'][0]['title'],'Platform Engineer')
        with cursor() as cur:
            cur.execute("UPDATE drafts SET status='spam',updated_at=clock_timestamp() WHERE draft_id=%s",(draft,))
        sync_company_batch()
        self.assertEqual(list_companies(self.domain)['total_count'],0)

    def test_deleted_source_cascades_without_orphan_evidence(self):
        draft=self.add();sync_company_batch()
        with cursor() as cur:cur.execute('DELETE FROM drafts WHERE draft_id=%s',(draft,))
        self.assertEqual(list_companies(self.domain)['total_count'],0)

class CompanyAccessTests(unittest.TestCase):
    def test_directory_requires_existing_draft_read_permission(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.security.rbac import get_current_user
        app.dependency_overrides[get_current_user]=lambda:{'permissions':[]}
        try:
            with TestClient(app) as client:
                self.assertEqual(client.get('/companies').status_code,403)
        finally:
            app.dependency_overrides.pop(get_current_user,None)

    def test_pagination_is_bounded(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.security.rbac import get_current_user
        app.dependency_overrides[get_current_user]=lambda:{'permissions':['drafts:read']}
        try:
            with TestClient(app) as client:
                self.assertEqual(client.get('/companies?page_size=10000').status_code,422)
                self.assertEqual(client.get('/companies?page=0').status_code,422)
                self.assertEqual(client.get('/companies').status_code,200)
        finally:
            app.dependency_overrides.pop(get_current_user,None)
