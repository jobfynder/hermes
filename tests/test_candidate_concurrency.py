import os, unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from app.runtime.db import cursor, init_schema
from app.understanding.taxonomy.candidates import _upsert_candidate, candidate_identity

class CandidateConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv('HERMES_RELIABILITY_TEST_DB') != '1':
            raise unittest.SkipTest('Synthetic database only')
        init_schema()

    def test_concurrent_variants_share_one_review(self):
        prefix = 'Fixture' + uuid4().hex
        terms = [prefix + '.JS', prefix + ' JS', prefix + 'JS'] * 4
        try:
            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(lambda term: _upsert_candidate('skill', term, None, 'example.invalid'), terms))
            with cursor() as cur:
                cur.execute('SELECT occurrence_count FROM taxonomy_candidates WHERE normalized_term LIKE %s', (prefix.lower()+'%',))
                rows = cur.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['occurrence_count'], 12)
        finally:
            with cursor() as cur:
                cur.execute('DELETE FROM taxonomy_candidates WHERE normalized_term LIKE %s', (prefix.lower()+'%',))

    def test_language_punctuation_is_significant(self):
        self.assertEqual(len({candidate_identity(t) for t in ('C','C++','C#')}), 3)
