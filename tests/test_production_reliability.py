import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
from uuid import uuid4

from app.drafts import backfill
from app.runtime.db import cursor, init_schema
from app.understanding.taxonomy import loader, signals


class TaxonomyCacheTests(unittest.TestCase):
    def test_source_reload_invalidates_derived_cache(self):
        source = {'skills': []}
        with patch.object(loader, 'load_canonical_skills_taxonomy', side_effect=lambda: source):
            calls = []
            @loader.cache_by_taxonomy
            def build():
                calls.append(1)
                return len(calls)
            self.assertEqual(build(), 1)
            self.assertEqual(build(), 1)
            source = {'skills': [{'name': 'NewSkill'}]}
            self.assertEqual(build(), 2)

    def test_patterns_preserve_boundaries(self):
        pattern = signals._safe_phrase_pattern('C++')
        self.assertEqual([m.group() for m in pattern.finditer('C++ and XC++Y')], ['C++'])

    def test_prefilter_preserves_unicode_ignorecase(self):
        candidates = [signals.SignalCandidate('skill', 'skill', 'skill', 'canonical', 'high')]
        self.assertEqual(len(signals._extract_candidates('ſkİll', candidates)), 1)


class ConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('graph_consumer_test', Path('scripts/hermes-850-graph-notification-consumer.py'))
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_processing_is_dispatched_without_ack(self):
        module = self.module
        channel, method = Mock(), Mock()
        executor = Mock()
        with patch.object(module, '_executor', executor), patch.object(module, '_pending', []):
            module._on_message(channel, method, None, json.dumps({'notification': {'resource': 'test'}}).encode())
            executor.submit.assert_called_once()
            channel.basic_ack.assert_not_called()
            self.assertEqual(len(module._pending), 1)

    def test_retry_is_confirmed_before_ack(self):
        module = self.module
        channel, method = Mock(), Mock()
        with patch.object(module, '_publish', side_effect=RuntimeError('not confirmed')):
            with self.assertRaises(RuntimeError):
                module._finish_message(channel, method, {'notification': {}}, 'error')
        channel.basic_ack.assert_not_called()

    def test_missing_graph_message_is_preserved_without_retry(self):
        module = self.module
        channel, method = Mock(), Mock()
        with patch.object(module, '_publish_dead_letter') as publish:
            module._finish_message(channel, method, {'notification': {}}, {'code':'fetch_http_404','retry_after':0})
            publish.assert_called_once()
        channel.basic_ack.assert_called_once()

    def test_graph_retry_after_is_respected(self):
        module = self.module
        channel, method = Mock(), Mock()
        with patch.object(module, '_publish') as publish:
            module._finish_message(channel, method, {'notification': {}}, {'code':'fetch_http_429','retry_after':60})
            self.assertEqual(publish.call_args.kwargs['expiration_ms'], 60000)


class BackfillIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_schema()

    def setUp(self):
        # This suite MUST run only in the dedicated hermes-fix-test database.
        import os
        self.assertTrue('hermes-fix-test-db' in os.environ['DATABASE_URL'] or os.getenv('HERMES_RELIABILITY_TEST_DB') == '1')
        with cursor() as cur:
            cur.execute('DELETE FROM draft_backfill_items')
            cur.execute('DELETE FROM draft_backfill_jobs')
        self.ids = []
        for i in range(3):
            draft_id = uuid4()
            self.ids.append(draft_id)
            with cursor() as cur:
                cur.execute('''INSERT INTO drafts(draft_id,draft_type,status,source,payload,created_at)
                    VALUES (%s,'draft_job_requirement','needs_review','reliability_test',%s,'2000-01-01')''',
                    (draft_id, json.dumps({'text': 'Test', 'structured_data': {'email_parsing': {'confidence': 0.5, 'records': []}}})))

    def test_review_reparse_excludes_ready_drafts(self):
        with cursor() as cur:
            cur.execute("UPDATE drafts SET status='draft' WHERE draft_id=%s", (self.ids[0],))
        job_id = uuid4()
        job = backfill.create_job(job_id, 'review-reparse', dry_run=True)
        self.assertEqual(job['total_count'], 2)
        with cursor() as cur:
            cur.execute('SELECT draft_id FROM draft_backfill_items WHERE job_id=%s', (job_id,))
            self.assertNotIn(self.ids[0], [row['draft_id'] for row in cur.fetchall()])

    def tearDown(self):
        with cursor() as cur:
            cur.execute('DELETE FROM field_provenance WHERE parse_run_id=ANY(%s)', ([str(i) for i in self.ids],))
            cur.execute('DELETE FROM drafts WHERE draft_id=ANY(%s)', (self.ids,))
            cur.execute('DELETE FROM draft_backfill_items')
            cur.execute('DELETE FROM draft_backfill_jobs')

    @staticmethod
    def result(row, *_):
        return {'payload': {'text': 'Test', 'new_field': 'fixed'}, 'parsing': {'confidence': 0.5, 'requires_review': True},
                'status': 'needs_review', 'entries': [], 'changed': True}

    def test_idempotency_pause_resume_and_durable_progress(self):
        job_id = uuid4()
        job = backfill.create_job(job_id, 'full-reparse', False, 1, 3)
        self.assertEqual(job['total_count'], 3)
        self.assertEqual(backfill.create_job(job_id, 'full-reparse', False, 1, 3)['job_id'], job_id)
        with self.assertRaises(ValueError):
            backfill.create_job(job_id, 'full-reparse', True, 1, 3)
        with patch.object(backfill, 'prepare_row', side_effect=self.result):
            backfill.run_batch(job_id)
            self.assertEqual(backfill.get_job(job_id)['processed_count'], 1)
            backfill.control_job(job_id, 'pause')
            self.assertFalse(backfill.run_batch(job_id))
            backfill.control_job(job_id, 'resume')
            backfill.run_batch(job_id)
            backfill.run_batch(job_id)
        job = backfill.get_job(job_id)
        self.assertEqual((job['status'], job['processed_count'], job['changed_count']), ('completed', 3, 3))

    def test_atomic_rollback_and_resume_after_failure(self):
        job_id = uuid4()
        backfill.create_job(job_id, 'full-reparse', False, 3, 3)
        with patch.object(backfill, 'prepare_row', side_effect=self.result), patch.object(backfill, 'record_field_provenance', side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError):
                backfill.run_batch(job_id)
        self.assertEqual(backfill.get_job(job_id)['processed_count'], 0)
        with cursor() as cur:
            cur.execute('SELECT count(*) AS n FROM drafts WHERE draft_id=ANY(%s) AND payload ? %s', (self.ids, 'new_field'))
            self.assertEqual(cur.fetchone()['n'], 0)
        with patch.object(backfill, 'prepare_row', side_effect=self.result):
            backfill.run_batch(job_id)
        self.assertEqual(backfill.get_job(job_id)['processed_count'], 3)

    def test_concurrent_edit_is_preserved(self):
        job_id = uuid4()
        backfill.create_job(job_id, 'full-reparse', False, 3, 3)
        def edit(row, *args):
            with cursor() as cur:
                cur.execute("UPDATE drafts SET payload=%s,updated_at=now() WHERE draft_id=%s", (json.dumps({'human': True}), row['draft_id']))
            return self.result(row)
        with patch.object(backfill, 'prepare_row', side_effect=edit):
            backfill.run_batch(job_id)
        self.assertEqual(backfill.get_job(job_id)['skipped_count'], 3)

    def test_dry_run_changes_only_job_metadata(self):
        job_id = uuid4()
        backfill.create_job(job_id, 'full-reparse', True, 3, 3)
        with patch.object(backfill, 'prepare_row', side_effect=self.result):
            backfill.run_batch(job_id)
        self.assertEqual(backfill.get_job(job_id)['changed_count'], 3)
        with cursor() as cur:
            cur.execute('SELECT count(*) AS n FROM drafts WHERE draft_id=ANY(%s) AND payload ? %s', (self.ids, 'new_field'))
            self.assertEqual(cur.fetchone()['n'], 0)

    def test_equal_confidence_field_changes_are_detected(self):
        row = {'payload': {'text': 'Test', 'structured_data': {'email_parsing': {'confidence': 0.5, 'records': []}}},
               'status': 'needs_review', 'confidence': 0.5, 'requires_review': True}
        parsed = {'confidence': 0.5, 'requires_review': True, 'records': [], 'new_field': 'fixed'}
        with patch.object(backfill, 'parse_email_business_records', return_value=parsed), patch.object(backfill, 'parse_email_signature', return_value={}), patch.object(backfill, 'apply_signature_company_fill', return_value=(parsed,False)):
            self.assertTrue(backfill.prepare_row(row, 'full-reparse', frozenset())['changed'])

    def test_intake_failure_rolls_back_dedupe_key(self):
        from app.runtime.db import transaction
        from app.runtime.intake_log import record_idempotency_key_if_new
        key = 'reliability-test-' + str(uuid4())
        with self.assertRaises(RuntimeError):
            with transaction():
                self.assertTrue(record_idempotency_key_if_new(key))
                raise RuntimeError('crash before draft commit')
        self.assertTrue(record_idempotency_key_if_new(key))
        with cursor() as cur:
            cur.execute('DELETE FROM idempotency_keys WHERE key=%s', (key,))

    def test_concurrent_schema_initialization(self):
        from concurrent.futures import ThreadPoolExecutor
        from app.runtime import db
        table = 'schema_race_' + uuid4().hex
        with patch.object(db, 'SCHEMA', f'CREATE TABLE IF NOT EXISTS {table}(id INTEGER)'):
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(db.init_schema) for _ in range(4)]
                for future in futures:
                    future.result()
        with cursor() as cur:
            cur.execute(f'DROP TABLE {table}')

    def test_schema_waits_for_intake_before_taking_table_locks(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from app.runtime import db
        entered = Event()
        with patch.object(db, 'SCHEMA', 'SELECT 1'):
            with ThreadPoolExecutor(max_workers=1) as pool:
                with db.transaction():
                    def initialize():
                        entered.set()
                        db.init_schema()
                    future = pool.submit(initialize)
                    self.assertTrue(entered.wait(2))
                    self.assertFalse(future.done())
                future.result(timeout=5)


if __name__ == '__main__':
    unittest.main()
