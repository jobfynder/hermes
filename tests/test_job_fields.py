"""Job-board field extraction and the Core push contract. Pure functions, no
database; texts are shaped like real recruiter mail with identities removed."""
import unittest

from app.drafts.models import DraftObject
from app.email_parsing.job_fields import (
    extract_job_board_fields,
    infer_employment_type,
    parse_duration,
    parse_rate,
    parse_requisition_id,
    parse_work_mode,
)
from app.integrations.core_job_push import map_draft_to_core_job_payload


class EmploymentTypeTests(unittest.TestCase):
    def test_duration_is_evidence_of_contract(self):
        text = 'Data Engineer\nLocation: Dallas, TX\nDuration: 12 months\n'
        self.assertEqual(infer_employment_type(text, parse_duration(text)), ('Contract', 'duration'))

    def test_stated_label_wins(self):
        text = 'Job Type: Full Time\nDuration: 12 months'
        self.assertEqual(infer_employment_type(text, parse_duration(text)), ('Full-time', 'label'))

    def test_no_evidence_is_not_guessed(self):
        self.assertEqual(infer_employment_type('Java Developer in Austin', {}), (None, None))

    def test_experience_years_are_not_a_duration(self):
        self.assertEqual(parse_duration('Must have 8+ years of experience in Java'), {})
        self.assertEqual(parse_duration('6 months experience with AWS required'), {})

    def test_existing_value_is_never_replaced(self):
        out = extract_job_board_fields('Duration: 12 months', None, {'employment_type': 'W2'})
        self.assertNotIn('employment_type', out)
        self.assertEqual(out['duration_months'], 12)


class RateTests(unittest.TestCase):
    def test_hourly_range_with_basis(self):
        rate = parse_rate('Pay Rate: $60-65/hr on C2C')
        self.assertEqual((rate['rate_min'], rate['rate_max'], rate['rate_unit']), (60.0, 65.0, 'hour'))
        self.assertEqual(rate['rate_basis'], 'C2C')

    def test_annual(self):
        rate = parse_rate('Salary: $120k per year')
        self.assertEqual((rate['rate_min'], rate['rate_unit']), (120000.0, 'year'))

    def test_boilerplate_and_unrelated_money_ignored(self):
        self.assertEqual(parse_rate('Post jobs from just $499/month on our board'), {})
        self.assertEqual(parse_rate('The client has a $2 million budget'), {})


class WorkModeTests(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(parse_work_mode('Fully remote role'), 'REMOTE')
        self.assertEqual(parse_work_mode('Hybrid - 3 days onsite'), 'HYBRID')
        self.assertEqual(parse_work_mode('Onsite in Plano, TX'), 'ONSITE')
        self.assertIsNone(parse_work_mode('Great opportunity in Plano, TX'))

    def test_negation(self):
        self.assertEqual(parse_work_mode('This role is not remote. Onsite only.'), 'ONSITE')

    def test_subject_is_consulted(self):
        self.assertEqual(parse_work_mode('see below', subject='Sr Java Dev - Hybrid - Dallas'), 'HYBRID')


class RequisitionTests(unittest.TestCase):
    def test_requires_a_digit(self):
        self.assertEqual(parse_requisition_id('Job ID: ABC-12345'), 'ABC-12345')
        self.assertIsNone(parse_requisition_id('Job ID: details below'))


class CoreContractTests(unittest.TestCase):
    """Fields Core's CreateParsedJobDto requires must always be produced."""

    def draft(self, **record):
        base = {'job_title': 'Data Engineer', 'location': 'Dallas, TX', 'required_skills': ['Python']}
        return DraftObject(
            draft_id='d1', draft_type='draft_job_requirement', source='email',
            payload={'structured_data': {'email_parsing': {'records': [{**base, **record}]}}},
            metadata={'sender': {'email': 'r@vendor.com'}},
        )

    def test_required_core_fields_present(self):
        payload = map_draft_to_core_job_payload(self.draft(employment_type='Contract'))
        self.assertEqual(payload['jobTitle'], 'Data Engineer')
        self.assertEqual(payload['employmentTypes'], ['Contract'])
        self.assertIn(payload['workLocation'], ('REMOTE', 'HYBRID', 'ONSITE'))
        self.assertEqual(payload['externalSource']['sourceType'], 'EMAIL')

    def test_structured_work_mode_and_rate_win(self):
        payload = map_draft_to_core_job_payload(
            self.draft(employment_type='Contract', work_mode='HYBRID', rate_min=60.0, rate_max=65.0, rate_unit='hour')
        )
        self.assertEqual(payload['workLocation'], 'HYBRID')
        self.assertEqual((payload['minRate'], payload['maxRate'], payload['rateType']), (60.0, 65.0, 'PER_HOUR'))


if __name__ == '__main__':
    unittest.main()
