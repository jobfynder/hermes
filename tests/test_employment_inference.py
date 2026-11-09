"""More evidence for a missing employment type (text rules + sender history)."""
import json
import os
import unittest
from uuid import uuid4

from app.drafts import employment_priors
from app.email_parsing.job_fields import (
    employment_type_from_keywords,
    extract_job_board_fields,
    infer_employment_type,
    parse_duration,
    parse_rate,
)
from app.runtime.db import cursor, init_schema


def infer(text, subject=None):
    return infer_employment_type(text, parse_duration(text), subject, parse_rate(text))


class TextEvidence(unittest.TestCase):
    def test_label_glued_to_next_heading(self):
        self.assertEqual(infer("Employment Type: ContractJob Summary\nBuild things"), ("Contract", "label"))

    def test_subject_pipe_delimited(self):
        self.assertEqual(infer("Build ETL pipelines", "Android Developer || Contract || Onsite"), ("Contract", "keyword"))

    def test_contract_position_and_w2(self):
        self.assertEqual(infer("This is a contract position in Dallas")[0], "Contract")
        self.assertEqual(infer("Must be available to work on W2 or C2C")[0], "Contract")

    def test_permanent_role(self):
        self.assertEqual(infer("Permanent role with benefits at our Austin office")[0], "Full-time")

    def test_contract_to_hire_wins(self):
        self.assertEqual(infer("Contract to hire opportunity, contract position")[0], "Contract to Hire")

    def test_negated_mentions_are_not_evidence(self):
        self.assertIsNone(employment_type_from_keywords(None, "No C2C. No third party vendors."))
        self.assertIsNone(employment_type_from_keywords(None, "C2C is not accepted for this role"))

    def test_incidental_words_are_not_evidence(self):
        for text in ("Develop API contracts between services", "Work full time onsite with the client team",
                     "Government contracts experience preferred", "Employees get full-time benefits"):
            self.assertIsNone(employment_type_from_keywords(None, text), text)

    def test_mixed_evidence_is_not_guessed(self):
        self.assertIsNone(employment_type_from_keywords("Java Developer (Contract / Permanent)", ""))

    def test_duration_window_and_longterm_line(self):
        self.assertEqual(infer("Duration: 11/16/2026 - 06/30/2027\nPython")[0], "Contract")
        self.assertEqual(infer("Skills\nPython\nLongterm\nDallas")[0], "Contract")
        self.assertIsNone(infer("Build long-term vision for the platform")[0])

    def test_hourly_rate_means_contract_and_salary_means_permanent(self):
        self.assertEqual(infer("Pay: $65/hr")[:2], ("Contract", "hourly_rate"))
        self.assertEqual(infer("Salary: $140,000 per year")[:2], ("Full-time", "salary"))

    def test_extractor_fills_only_when_empty_and_flags_basis(self):
        out = extract_job_board_fields("Python dev. 6 month contract", None, {"employment_type": None})
        self.assertEqual((out["employment_type"], out["employment_type_basis"]), ("Contract", "keyword"))
        self.assertNotIn("employment_type", extract_job_board_fields("6 month contract", None, {"employment_type": "Full-time"}))


def post(sender, employment=None, basis=None, status='draft', age_days=1):
    draft_id = uuid4()
    rec = {'job_title': 'Dev', 'location': 'Dallas, TX', 'required_skills': ['Python'], 'employment_type': employment}
    if basis:
        rec['employment_type_basis'] = basis
    with cursor() as cur:
        cur.execute(
            """INSERT INTO drafts(draft_id,draft_type,status,source,payload,metadata,created_at)
               VALUES (%s,'draft_job_requirement',%s,'priors_test',%s,%s, now() - make_interval(days => %s))""",
            (draft_id, status, json.dumps({'structured_data': {'email_parsing': {'records': [rec]}}}),
             json.dumps({'sender': {'email': sender}}), age_days),
        )
    return str(draft_id)


def record_of(draft_id):
    with cursor() as cur:
        cur.execute("SELECT payload->'structured_data'->'email_parsing'->'records'->0 AS rec FROM drafts WHERE draft_id=%s", (draft_id,))
        return cur.fetchone()['rec']


class SenderHistory(unittest.TestCase):
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
            cur.execute("DELETE FROM sender_employment_priors")
            cur.execute("DELETE FROM field_provenance WHERE parse_run_id IN (SELECT draft_id::text FROM drafts WHERE source='priors_test')")
            cur.execute("DELETE FROM drafts WHERE source='priors_test'")

    def test_learns_from_stated_values_and_fills_blank_posts(self):
        for _ in range(9):
            post('steady@vendor.com', 'Contract')
        blank = post('steady@vendor.com')
        self.assertEqual(employment_priors.refresh_priors()['upserted'], 1)
        self.assertEqual(employment_priors.fill_from_priors()['filled'], 1)
        rec = record_of(blank)
        self.assertEqual((rec['employment_type'], rec['employment_type_basis']), ('Contract', 'sender_history'))

    def test_mixed_or_thin_senders_get_no_prior(self):
        for _ in range(5):
            post('mixed@vendor.com', 'Contract')
            post('mixed@vendor.com', 'Full-time')
        for _ in range(3):
            post('thin@vendor.com', 'Contract')
        post('mixed@vendor.com')
        post('thin@vendor.com')
        self.assertEqual(employment_priors.refresh_priors()['upserted'], 0)
        self.assertEqual(employment_priors.fill_from_priors()['filled'], 0)

    def test_inferred_values_never_become_evidence(self):
        for _ in range(10):
            post('guesser@vendor.com', 'Contract', basis='sender_history')
        self.assertEqual(employment_priors.refresh_priors()['upserted'], 0)

    def test_existing_value_and_human_edits_are_never_touched(self):
        for _ in range(9):
            post('steady@vendor.com', 'Contract')
        has = post('steady@vendor.com', 'Full-time')
        edited = post('steady@vendor.com')
        with cursor() as cur:
            cur.execute("INSERT INTO field_provenance(parse_run_id,field_path,extractor,extraction_method,confidence,value_kind) "
                        "VALUES (%s,'job.company','reviewer_correction','deterministic',1.0,'text')", (edited,))
        employment_priors.refresh_priors()
        employment_priors.fill_from_priors()
        self.assertEqual(record_of(has)['employment_type'], 'Full-time')
        self.assertFalse(record_of(edited).get('employment_type'))

    def test_kill_switch(self):
        os.environ['HERMES_EMPLOYMENT_PRIORS_ENABLED'] = '0'
        try:
            self.assertEqual(employment_priors.run_step(), {'enabled': False})
        finally:
            os.environ.pop('HERMES_EMPLOYMENT_PRIORS_ENABLED', None)


if __name__ == '__main__':
    unittest.main()
