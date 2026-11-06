"""Taxonomy and blocklist review automation. Synthetic database only: these
functions act on every matching row in the database they are pointed at."""
import json
import os
import unittest
from uuid import uuid4

from app.email_parsing import auto_blocklist
from app.runtime.db import cursor, init_schema
from app.understanding.taxonomy import automation


def candidate(term, signal='skill', occurrences=1, senders=(), status='pending', reviewed_by=None, last_seen_days=0):
    with cursor() as cur:
        cur.execute(
            """INSERT INTO taxonomy_candidates(signal_type,term,normalized_term,occurrence_count,distinct_senders,
                   status,reviewed_by,last_seen_at) VALUES (%s,%s,%s,%s,%s,%s,%s, now() - make_interval(days => %s))
               RETURNING id""",
            (signal, term, term.lower(), occurrences, json.dumps(list(senders)), status, reviewed_by, last_seen_days),
        )
        return cur.fetchone()['id']


def status_of(candidate_id):
    with cursor() as cur:
        cur.execute('SELECT status, reviewed_by FROM taxonomy_candidates WHERE id=%s', (candidate_id,))
        row = cur.fetchone()
        return row['status'], row['reviewed_by']


def post(sender, status, reason=None, age_days=5):
    with cursor() as cur:
        cur.execute(
            """INSERT INTO drafts(draft_id,draft_type,status,source,payload,metadata,created_at)
               VALUES (%s,'draft_job_requirement',%s,'automation_test','{}',%s, now() - make_interval(days => %s))""",
            (uuid4(), status, json.dumps({'sender': {'email': sender}, **({'rejection_reason': reason} if reason else {})}), age_days),
        )


class DbCase(unittest.TestCase):
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
            cur.execute("DELETE FROM taxonomy_candidates WHERE term LIKE 'zzauto%'")
            cur.execute("DELETE FROM drafts WHERE source='automation_test'")
            cur.execute("DELETE FROM sender_blocklist WHERE reason LIKE 'auto:%' OR value LIKE '%autotest%'")
            cur.execute('DELETE FROM review_automation_runs')


class TaxonomyAutomationTests(DbCase):
    def test_single_sender_template_is_rejected_multi_sender_kept(self):
        template = candidate('zzauto Interview Time Availability', occurrences=63, senders=['vendor.com'])
        real = candidate('zzauto Guidewire', occurrences=63, senders=['a.com', 'b.com', 'c.com'])
        automation.reject_single_sender_templates()
        self.assertEqual(status_of(template), ('rejected', 'hermes-auto-template'))
        self.assertEqual(status_of(real)[0], 'pending')

    def test_stale_one_off_is_retired_fresh_is_kept(self):
        stale = candidate('zzauto stale term', occurrences=1, senders=['a.com'], last_seen_days=45)
        fresh = candidate('zzauto fresh term', occurrences=1, senders=['a.com'], last_seen_days=2)
        multi = candidate('zzauto multi term', occurrences=2, senders=['a.com', 'b.com'], last_seen_days=45)
        automation.retire_stale_observations()
        self.assertEqual(status_of(stale)[0], 'rejected')
        self.assertEqual(status_of(fresh)[0], 'pending')
        self.assertEqual(status_of(multi)[0], 'pending')

    def test_auto_rejected_term_is_revived_but_human_rejection_is_not(self):
        auto = candidate('zzauto grown', occurrences=9, senders=['a.com', 'b.com', 'c.com'], status='rejected',
                         reviewed_by='hermes-stale-observation')
        human = candidate('zzauto human', occurrences=9, senders=['a.com', 'b.com', 'c.com'], status='rejected',
                          reviewed_by='pavan-admin')
        automation.revive_recovered_candidates()
        self.assertEqual(status_of(auto)[0], 'pending')
        self.assertEqual(status_of(human), ('rejected', 'pavan-admin'))

    def test_scheduler_runs_only_when_due_and_survives_errors(self):
        now = [0.0]
        calls = []
        sched = automation.ReviewAutomationScheduler(
            check_seconds=600, first_delay_seconds=10, clock=lambda: now[0],
            runner=lambda: calls.append(1) or {}, due=lambda: True,
        )
        self.assertFalse(sched.tick())
        now[0] = 11
        self.assertTrue(sched.tick())
        now[0] = 12
        self.assertFalse(sched.tick())  # inside the check interval
        boom = automation.ReviewAutomationScheduler(
            check_seconds=1, first_delay_seconds=0, clock=lambda: 5.0,
            runner=lambda: (_ for _ in ()).throw(RuntimeError('x')), due=lambda: True,
        )
        self.assertFalse(boom.tick())

    def test_kill_switch(self):
        os.environ['HERMES_REVIEW_AUTOMATION_ENABLED'] = '0'
        try:
            sched = automation.ReviewAutomationScheduler(first_delay_seconds=0, clock=lambda: 1.0, due=lambda: True,
                                                         runner=lambda: self.fail('must not run'))
            self.assertFalse(sched.tick())
        finally:
            del os.environ['HERMES_REVIEW_AUTOMATION_ENABLED']

    def test_full_pass_records_a_run(self):
        candidate('zzauto Interview Time Availability', occurrences=20, senders=['vendor.com'])
        summary = automation.run_review_automation()
        self.assertEqual(summary['taxonomy']['templates_rejected'] >= 1, True)
        self.assertIsNotNone(automation.last_run())


class AutoBlocklistTests(DbCase):
    def test_free_mail_address_with_repeated_review_rejections_is_blocked(self):
        for _ in range(8):
            post('spammer.autotest@gmail.com', 'rejected', reason='bulk dashboard review')
        result = auto_blocklist.run_auto_blocklist()
        self.assertIn(('email', 'spammer.autotest@gmail.com'), [(a['match_type'], a['value']) for a in result['added']])

    def test_address_with_a_usable_post_or_only_duplicates_is_not_blocked(self):
        for _ in range(7):
            post('good.autotest@gmail.com', 'rejected', reason='bulk dashboard review')
        post('good.autotest@gmail.com', 'draft')
        for _ in range(9):
            post('dupes.autotest@gmail.com', 'rejected', reason='exact_duplicate')
        result = auto_blocklist.run_auto_blocklist()
        blocked = [a['value'] for a in result['added']]
        self.assertNotIn('good.autotest@gmail.com', blocked)
        self.assertNotIn('dupes.autotest@gmail.com', blocked)

    def test_shared_domain_is_never_blocked_company_domain_can_be(self):
        for _ in range(25):
            post('x@gmail.com', 'needs_review')
            post('x@noise-autotest.com', 'needs_review')
        result = auto_blocklist.run_auto_blocklist()
        domains = [a['value'] for a in result['added'] if a['match_type'] == 'domain']
        self.assertIn('noise-autotest.com', domains)
        self.assertNotIn('gmail.com', domains)

    def test_cap_per_run(self):
        for i in range(3):
            for _ in range(8):
                post(f'cap{i}.autotest@gmail.com', 'rejected', reason='bulk dashboard review')
        self.assertEqual(auto_blocklist.run_auto_blocklist(max_blocks=2)['blocked'], 2)


if __name__ == '__main__':
    unittest.main()
