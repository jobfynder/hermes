import os
import unittest
from app.runtime.db import cursor,init_schema
from app.understanding.taxonomy.candidates import _find_loosely_matching_pending_candidate
from app.understanding.taxonomy.loader import normalize_taxonomy_key

class CandidateLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv('HERMES_RELIABILITY_TEST_DB')!='1':
            raise unittest.SkipTest('Synthetic database only')
        init_schema()

    def setUp(self):
        self.ids=[]

    def tearDown(self):
        with cursor() as cur:
            cur.execute('DELETE FROM taxonomy_candidates WHERE id=ANY(%s)',(self.ids,))

    def add(self,kind,term,status='pending'):
        with cursor() as cur:
            cur.execute('INSERT INTO taxonomy_candidates(signal_type,term,normalized_term,status) VALUES (%s,%s,%s,%s) RETURNING id',(kind,term,normalize_taxonomy_key(term),status))
            value=cur.fetchone()['id'];self.ids.append(value);return value

    def test_punctuation_match_and_missing(self):
        expected=self.add('skill','LookupFixture.Node.JS')
        with cursor() as cur:
            self.assertEqual(_find_loosely_matching_pending_candidate(cur,'skill','LookupFixtureNodeJS')['id'],expected)
            self.assertIsNone(_find_loosely_matching_pending_candidate(cur,'skill','UnseenLookupFixture'))

    def test_status_and_kind_are_respected(self):
        self.add('skill','LookupFixture.Approved','approved')
        self.add('job_title','LookupFixture.Other')
        with cursor() as cur:
            self.assertIsNone(_find_loosely_matching_pending_candidate(cur,'skill','LookupFixtureApproved'))
            self.assertIsNone(_find_loosely_matching_pending_candidate(cur,'skill','LookupFixtureOther'))

    def test_boilerplate_uses_same_normalization(self):
        expected=self.add('boilerplate_line','LookupFixture: Detailed requirement, with punctuation!')
        with cursor() as cur:
            self.assertEqual(_find_loosely_matching_pending_candidate(cur,'boilerplate_line','LookupFixture Detailed requirement with punctuation')['id'],expected)

    def test_index_supports_lookup(self):
        with cursor() as cur:
            cur.execute('SET LOCAL enable_seqscan=off')
            cur.execute("EXPLAIN SELECT id FROM taxonomy_candidates WHERE signal_type='boilerplate_line' AND status='pending' AND regexp_replace(normalized_term, '[^a-z0-9]', '', 'g')='fixture' ORDER BY id LIMIT 1")
            self.assertIn('idx_taxonomy_candidates_pending_loose',' '.join(str(r) for r in cur.fetchall()))
