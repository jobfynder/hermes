import contextlib, importlib.util, io, json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from app.runtime.db import cursor, init_schema
from app.understanding.taxonomy.candidates import _upsert_candidate
from app.understanding.taxonomy.loader import normalize_taxonomy_key

class TaxonomyCleanupTests(unittest.TestCase):
    def test_merge_preserves_aliases_counts_and_is_idempotent(self):
        if os.getenv('HERMES_RELIABILITY_TEST_DB') != '1':
            self.skipTest('Synthetic database only')
        init_schema()
        spec=importlib.util.spec_from_file_location('dedup_test',Path(__file__).parents[1]/'scripts/hermes-taxonomy-deduplicate.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        prefix='MergeFixture'+uuid4().hex
        ids=[]
        try:
            with cursor() as cur:
                for term in (prefix+'.JS',prefix+' JS'):
                    cur.execute("INSERT INTO taxonomy_candidates(signal_type,term,normalized_term) VALUES ('skill',%s,%s) RETURNING id",(term,normalize_taxonomy_key(term)))
                    ids.append(cur.fetchone()['id'])
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                (root/'canonical_skills.json').write_text(json.dumps({'skills':[{'name':'ServiceNow'},{'name':'Service Now'},{'name':'C'},{'name':'C++'},{'name':'C#'}]}))
                (root/'job_titles.json').write_text('{"titles":[]}')
                with patch.object(module,'_writable_taxonomy_path',side_effect=lambda name:root/name),patch.object(module,'clear_taxonomy_cache'),contextlib.redirect_stdout(io.StringIO()):
                    module.run(True)
                    module.run(True)
                entries=json.loads((root/'canonical_skills.json').read_text())['skills']
                self.assertEqual(len(entries),4)
                self.assertEqual(entries[0]['aliases'],['Service Now'])
                self.assertTrue(list(root.glob('dedup-backup-*/candidate-merges.jsonl')))
            _upsert_candidate('skill',prefix+' JS',None,'example.invalid')
            with cursor() as cur:
                cur.execute('SELECT status,occurrence_count FROM taxonomy_candidates WHERE id=%s',(ids[0],))
                winner=cur.fetchone()
                self.assertEqual(winner['status'],'pending')
                self.assertEqual(winner['occurrence_count'],3)
        finally:
            with cursor() as cur:
                cur.execute('DELETE FROM taxonomy_candidates WHERE id=ANY(%s)',(ids,))
