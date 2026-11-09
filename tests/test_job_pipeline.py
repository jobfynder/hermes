"""Cross-vendor de-duplication and the Core outbox. Synthetic database only."""
import json
import os
import unittest
from uuid import uuid4

from app.drafts import job_dedup
from app.integrations import core_outbox
from app.runtime.db import cursor, init_schema


def post(title='Data Engineer', location='Dallas, TX', skills=('Python', 'SQL', 'AWS'), employment='Contract',
         status='draft', email='r@vendor.com', age_days=1):
    draft_id = uuid4()
    rec = {'job_title': title, 'location': location, 'required_skills': list(skills), 'employment_type': employment}
    with cursor() as cur:
        cur.execute(
            """INSERT INTO drafts(draft_id,draft_type,status,source,payload,metadata,created_at)
               VALUES (%s,'draft_job_requirement',%s,'pipeline_test',%s,%s,
                       now() - make_interval(days => %s) + (random() * interval '1 minute'))""",
            (draft_id, status, json.dumps({'structured_data': {'email_parsing': {'records': [rec]}}}),
             json.dumps({'sender': {'email': email}}), age_days),
        )
    return str(draft_id)


class DbCase(unittest.TestCase):
    def setUp(self):
        if os.getenv('HERMES_RELIABILITY_TEST_DB') != '1':
            raise unittest.SkipTest('Synthetic database only')
        init_schema()
        self.clean()

    def tearDown(self):
        if os.getenv('HERMES_RELIABILITY_TEST_DB') == '1':
            self.clean()
        os.environ.pop('HERMES_CORE_PUSH_ENABLED', None)

    def clean(self):
        with cursor() as cur:
            cur.execute("DELETE FROM core_job_outbox")
            cur.execute("DELETE FROM job_cluster_members")
            cur.execute("DELETE FROM job_clusters")
            cur.execute("DELETE FROM job_unclusterable")
            cur.execute("DELETE FROM drafts WHERE source='pipeline_test'")


class DedupTests(DbCase):
    def test_same_role_from_two_vendors_is_one_cluster(self):
        a = post(age_days=2)
        post(location='Dallas TX', skills=('Python', 'SQL', 'Azure'))
        stats = job_dedup.cluster_new_drafts()
        self.assertEqual((stats['new_clusters'], stats['joined']), (1, 1))
        with cursor() as cur:
            cur.execute('SELECT count(*) AS n FROM job_clusters WHERE canonical_draft_id=%s', (a,))
            self.assertEqual(cur.fetchone()['n'], 1)

    def test_same_title_city_but_different_skills_stay_separate(self):
        post(skills=('Python', 'SQL', 'AWS'))
        post(skills=('Java', 'Spring', 'Kafka'))
        self.assertEqual(job_dedup.cluster_new_drafts()['new_clusters'], 2)

    def test_different_city_is_a_different_role(self):
        post()
        post(location='Austin, TX')
        self.assertEqual(job_dedup.cluster_new_drafts()['new_clusters'], 2)

    def test_no_title_is_unclusterable_and_not_retried(self):
        post(title='')
        self.assertEqual(job_dedup.cluster_new_drafts()['unclusterable'], 1)
        self.assertEqual(job_dedup.cluster_new_drafts()['examined'], 0)


class OutboxTests(DbCase):
    def test_one_ready_post_per_cluster_is_enqueued(self):
        post()
        post()
        post(title='QA Lead', skills=('Selenium',))
        job_dedup.cluster_new_drafts()
        self.assertEqual(core_outbox.enqueue_ready(), 2)
        self.assertEqual(core_outbox.enqueue_ready(), 0)  # idempotent

    def test_incomplete_or_review_posts_are_not_enqueued(self):
        post(employment=None)
        post(title='Other Role', status='needs_review')
        job_dedup.cluster_new_drafts()
        self.assertEqual(core_outbox.enqueue_ready(), 0)

    def test_better_duplicate_represents_a_cluster_whose_first_post_was_incomplete(self):
        post(employment=None, age_days=2)
        good = post(age_days=1)
        job_dedup.cluster_new_drafts()
        core_outbox.enqueue_ready()
        with cursor() as cur:
            cur.execute('SELECT draft_id FROM core_job_outbox')
            self.assertEqual([str(r['draft_id']) for r in cur.fetchall()], [good])

    def test_dispatch_is_off_by_default(self):
        post()
        job_dedup.cluster_new_drafts()
        core_outbox.enqueue_ready()
        self.assertEqual(core_outbox.dispatch(push=lambda d: self.fail('must not push')), {'enabled': False})

    def test_dispatch_pushes_and_records(self):
        os.environ['HERMES_CORE_PUSH_ENABLED'] = '1'
        post()
        job_dedup.cluster_new_drafts()
        core_outbox.enqueue_ready()
        result = core_outbox.dispatch(push=lambda d: {'status': 'pushed', 'core_job_id': 'job-1'})
        self.assertEqual(result['pushed'], 1)
        self.assertEqual(core_outbox.get_outbox_stats()['states'], {'pushed': 1})

    def test_failure_backs_off_and_opens_the_breaker(self):
        os.environ['HERMES_CORE_PUSH_ENABLED'] = '1'
        for i in range(6):
            post(title=f'Role {i}')
        job_dedup.cluster_new_drafts()
        core_outbox.enqueue_ready()

        def failing(draft):
            return {'status': 'failed', 'reason': 'http_400'}

        self.assertEqual(core_outbox.dispatch(batch=5, push=failing)['failed'], 5)
        self.assertEqual(core_outbox.dispatch(batch=5, push=failing).get('skipped'), 'circuit_open')
        with cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM core_job_outbox WHERE state='failed' AND next_attempt_at > now()")
            self.assertEqual(cur.fetchone()['n'], 5)

    def test_daily_cap(self):
        os.environ['HERMES_CORE_PUSH_ENABLED'] = '1'
        os.environ['HERMES_CORE_PUSH_DAILY_LIMIT'] = '1'
        try:
            for i in range(3):
                post(title=f'Capped {i}')
            job_dedup.cluster_new_drafts()
            core_outbox.enqueue_ready()

            def ok(draft):
                return {'status': 'pushed', 'core_job_id': 'x'}

            self.assertEqual(core_outbox.dispatch(push=ok)['pushed'], 1)
            self.assertEqual(core_outbox.dispatch(push=ok).get('skipped'), 'daily_limit')
        finally:
            os.environ.pop('HERMES_CORE_PUSH_DAILY_LIMIT', None)

    def test_removed_draft_is_held_not_pushed(self):
        os.environ['HERMES_CORE_PUSH_ENABLED'] = '1'
        draft_id = post()
        job_dedup.cluster_new_drafts()
        core_outbox.enqueue_ready()
        with cursor() as cur:
            cur.execute('DELETE FROM drafts WHERE draft_id=%s', (draft_id,))

        def gone(draft):
            raise AssertionError('must not push a removed draft')

        self.assertEqual(core_outbox.dispatch(push=gone)['held'], 1)


class SchedulerTests(unittest.TestCase):
    def test_runs_on_interval_and_survives_errors(self):
        now = [0.0]
        calls = []
        sched = core_outbox.PipelineScheduler(interval=60, first_delay=10, clock=lambda: now[0],
                                              steps=lambda: calls.append(1) or {'ok': True})
        self.assertIsNone(sched.tick())
        now[0] = 11
        self.assertEqual(sched.tick(), {'ok': True})
        now[0] = 12
        self.assertIsNone(sched.tick())

        def boom():
            raise RuntimeError('x')

        self.assertIsNone(core_outbox.PipelineScheduler(first_delay=0, clock=lambda: 1.0, steps=boom).tick())


if __name__ == '__main__':
    unittest.main()
