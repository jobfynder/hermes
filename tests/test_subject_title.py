"""Subject-line title fallback. Subjects are shaped like real recruiter mail
(company/people details removed); pure functions, no database."""
import unittest

from app.email_parsing.subject_title import extract_subject_title as t


class SubjectTitleTests(unittest.TestCase):
    def test_extracts_through_recruiter_noise(self):
        cases = {
            'Hiring!! SAP EAM Consultant (USC, TN and H4)': 'SAP EAM Consultant',
            'Contract || Data Ingestion Developer || Liberty, NC 27298 (Remote)': 'Data Ingestion Developer',
            'Now Hiring: Scrum Master-Charlotte, NC': 'Scrum Master',
            'Full Stack Python Developer Location: San Francisco Bay Area, CA': 'Full Stack Python Developer',
            'Contract || QA Lead || NJ': 'QA Lead',
        }
        for subject, expected in cases.items():
            with self.subTest(subject=subject):
                self.assertEqual(t(subject), expected)

    def test_urgent_requirement_double_colon(self):
        self.assertIn('data scientist', (t('Urgent Requirement :: Data Scientist (Remote) :: Franklin') or '').lower())

    def test_group_prefix_and_markup_removed(self):
        self.assertEqual(t('Group - Vendors & Clients Hub **HIRING: Oracle Fusion Consultant**'), 'Oracle Fusion Consultant')

    def test_leading_dot_of_dotnet_is_kept(self):
        self.assertTrue((t('.Net Lead') or '').startswith('.Net'))

    def test_non_job_subjects_return_none(self):
        for subject in ('60+ Pre-Screened Consultants', 'RTR', 'Contract', 'Immediate Interview', '', None):
            with self.subTest(subject=subject):
                self.assertIsNone(t(subject))


class ParserIntegrationTests(unittest.TestCase):
    def test_existing_title_is_never_replaced(self):
        from app.understanding.parsers.basic import extract_probable_title
        subject = 'Senior Java Developer | Remote'
        self.assertEqual(extract_probable_title(subject), 'Senior Java Developer')


if __name__ == '__main__':
    unittest.main()
