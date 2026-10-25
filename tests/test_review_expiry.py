"""Review-queue auto-expiry. Synthetic database only: expire_batch deletes
every eligible needs_review row in the database it is pointed at."""
import json
import os
import unittest
from uuid import uuid4

from app.drafts import expiry
from app.runtime.db import cursor, init_schema


def insert_draft(status='needs_review', age_days=10, **extra):
    draft_id = uuid4()
    with cursor() as cur:
        cur.execute(
            """INSERT INTO drafts(draft_id,draft_type,status,source,source_message_id,payload,metadata,created_at)
               VALUES (%s,'draft_job_requirement',%s,'expiry_test',%s,%s,%s, now() - make_interval(days => %s))""",
            (draft_id, status, f'expiry-{draft_id}', json.dumps({'text': 'Test'}),
             json.dumps(extra.get('metadata', {})), age_days),
        )
    return draft_id


def exists(draft_id):
    with cursor() as cur:
        cur.execute('SELECT 1 FROM drafts WHERE draft_id=%s', (draft_id,))
        return cur.fetchone() is not None


def archived(draft_id):
    with cursor() as cur:
        cur.execute('SELECT 1 FROM expired_review_drafts WHERE draft_id=%s', (draft_id,))
        return cur.fetchone() is not None


class ReviewExpiryTests(unittest.TestCase):
    def setUp(self):
        if os.getenv('HERMES_RELIABILITY_TEST_DB') != '1':
            raise unittest.SkipTest('Synthetic database only')
        init_schema()
        self.clean()

    def tearDown(self):
        if os.getenv('HERMES_RELIABILITY_TEST_DB') == '1':
            self.clean()

    def clean(self):
        with cursor() as cur:
            cur.execute("DELETE FROM field_provenance WHERE parse_run_id IN (SELECT draft_id::text FROM drafts WHERE source='expiry_test')")
            cur.execute("DELETE FROM email_claims WHERE draft_id IN (SELECT draft_id FROM drafts WHERE source='expiry_test')")
            cur.execute("DELETE FROM core_pushes WHERE draft_id IN (SELECT draft_id FROM drafts WHERE source='expiry_test')")
            cur.execute("DELETE FROM drafts WHERE source='expiry_test'")
            cur.execute("DELETE FROM expired_review_drafts WHERE snapshot->>'source'='expiry_test'")
            cur.execute('DELETE FROM review_expiry_runs')

    def test_old_needs_review_is_archived_and_removed(self):
        old = insert_draft(age_days=8)
        self.assertEqual(expiry.expire_batch(7, 100), 1)
        self.assertFalse(exists(old))
        self.assertTrue(archived(old))

    def test_recent_needs_review_is_kept(self):
        fresh = insert_draft(age_days=6)
        self.assertEqual(expiry.expire_batch(7, 100), 0)
        self.assertTrue(exists(fresh))

    def test_other_statuses_are_never_expired(self):
        ids = [insert_draft(status=s, age_days=90) for s in ('draft', 'published', 'rejected', 'spam')]
        self.assertEqual(expiry.expire_batch(7, 100), 0)
        self.assertTrue(all(exists(i) for i in ids))

    def test_human_corrected_draft_is_kept(self):
        corrected = insert_draft(age_days=30)
        with cursor() as cur:
            cur.execute(
                """INSERT INTO field_provenance(parse_run_id,field_path,extractor,extraction_method,confidence,value_kind)
                   VALUES (%s,'job_title','reviewer_correction','manual',1.0,'string')""",
                (str(corrected),),
            )
        self.assertEqual(expiry.expire_batch(7, 100), 0)
        self.assertTrue(exists(corrected))

    def test_core_push_reference_is_kept(self):
        pushed = insert_draft(age_days=30)
        with cursor() as cur:
            cur.execute("INSERT INTO core_pushes(draft_id,status) VALUES (%s,'failed')", (pushed,))
        self.assertEqual(expiry.expire_batch(7, 100), 0)
        self.assertTrue(exists(pushed))

    def test_batch_size_is_respected_and_reports_more(self):
        for _ in range(3):
            insert_draft(age_days=20)
        result = expiry.run_expiry_cycle(ttl_days=7, batch_size=2, archive_days=30)
        self.assertEqual((result['expired'], result['more']), (2, True))
        result = expiry.run_expiry_cycle(ttl_days=7, batch_size=2, archive_days=30)
        self.assertEqual((result['expired'], result['more']), (1, False))

    def test_disabled_when_ttl_is_zero(self):
        old = insert_draft(age_days=90)
        self.assertFalse(expiry.run_expiry_cycle(ttl_days=0)['enabled'])
        self.assertTrue(exists(old))

    def test_restore_returns_draft_with_fresh_clock(self):
        old = insert_draft(age_days=12)
        expiry.expire_batch(7, 100)
        self.assertEqual(expiry.restore_expired_draft(str(old)), {'restored': True})
        self.assertTrue(exists(old))
        self.assertFalse(archived(old))
        self.assertEqual(expiry.expire_batch(7, 100), 0)
        with cursor() as cur:
            cur.execute('SELECT status, metadata FROM drafts WHERE draft_id=%s', (old,))
            row = cur.fetchone()
        self.assertEqual(row['status'], 'needs_review')
        self.assertIn('restored_from_expiry', row['metadata'])

    def test_restore_unknown_draft_is_refused(self):
        self.assertEqual(expiry.restore_expired_draft(str(uuid4()))['reason'], 'not_in_archive')

    def test_old_archive_rows_are_purged(self):
        old = insert_draft(age_days=12)
        expiry.expire_batch(7, 100)
        with cursor() as cur:
            cur.execute("UPDATE expired_review_drafts SET expired_at = now() - interval '31 days' WHERE draft_id=%s", (old,))
        self.assertEqual(expiry.purge_archive(30), 1)
        self.assertFalse(archived(old))

    def test_status_reports_due_count(self):
        insert_draft(age_days=9)
        insert_draft(age_days=1)
        status = expiry.get_expiry_status()
        self.assertGreaterEqual(status['due_now'], 1)
        self.assertTrue(status['enabled'])


class SchedulerTests(unittest.TestCase):
    def test_waits_until_due_then_runs_and_backs_off(self):
        now = [0.0]
        calls = []

        def runner():
            calls.append(1)
            return {'expired': 5, 'more': False}

        sched = expiry.ReviewExpiryScheduler(interval_seconds=900, first_delay_seconds=60, clock=lambda: now[0], runner=runner)
        self.assertEqual(sched.tick(), 0)
        self.assertEqual(calls, [])
        now[0] = 61
        self.assertEqual(sched.tick(), 5)
        now[0] = 62
        sched.tick()
        self.assertEqual(len(calls), 1)
        now[0] = 61 + 901
        sched.tick()
        self.assertEqual(len(calls), 2)

    def test_full_batch_comes_back_quickly(self):
        now = [100.0]
        sched = expiry.ReviewExpiryScheduler(interval_seconds=900, first_delay_seconds=0, clock=lambda: now[0],
                                             runner=lambda: {'expired': 200, 'more': True})
        sched.tick()
        self.assertLessEqual(sched.next_due - now[0], 1.0)

    def test_runner_errors_never_escape(self):
        def boom():
            raise RuntimeError('db down')

        sched = expiry.ReviewExpiryScheduler(interval_seconds=900, first_delay_seconds=0, clock=lambda: 0.0, runner=boom)
        self.assertEqual(sched.tick(), 0)
        self.assertEqual(sched.next_due, 900)


if __name__ == '__main__':
    unittest.main()
