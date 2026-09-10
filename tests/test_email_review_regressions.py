import unittest
from app.understanding.parsers.basic import extract_probable_title
from app.email_parsing.parsers import _split_requirement_sections
from app.email_parsing.parsers import parse_requirement_email, apply_signature_company_fill
from app.email_parsing.signature import parse_email_signature


class EmailReviewRegressionTests(unittest.TestCase):
    def test_relay_banner_and_dotnet_posting_are_complete(self):
        text = 'Subject: .NET Developer || Onsite\n\nRemove/unsubscribe | Update your contact\n\nFrom :\nAlex Sample,\nExample Staffing\nalex@example.com\nReply to: alex@example.com\n\nSenior .NET / VB.NET Application Developer\nLocation: Example, PA\nRequired Skills: Python, SQL\nExperience: 3 years\nThanks & Regards,\nAlex Sample\nRole: Technical Recruiter'
        parsed = parse_requirement_email(text)
        parsed, _ = apply_signature_company_fill(parsed, parse_email_signature(text, sender_email='relay@example.net'))
        self.assertEqual(parsed['record_count'], 1)
        self.assertEqual(parsed['records'][0]['job_title'], 'Senior .NET / VB.NET Application Developer')
        self.assertFalse(parsed['requires_review'])
        self.assertIn('Required Skills', parsed['records'][0]['job_description'])

    def test_dotnet_subject(self):
        self.assertEqual(extract_probable_title('.NET Developer || ONSITE ROLE || Example, PA'), '.NET Developer')
        self.assertEqual(extract_probable_title('Need .Net Developer with Azure'), '.Net Developer')
        self.assertIsNone(extract_probable_title('.invalid Developer'))

    def test_common_title_formats(self):
        for text, expected in [
            ('Hiring for UX Designer with AI Experience - Multiple Locations', 'UX Designer'),
            ('Senior Software Development Engineer in Test (SDET)', 'Senior Software Development Engineer in Test (SDET)'),
            ('Urgent need for Java Developer || Remote', 'Java Developer'),
        ]:
            self.assertEqual(extract_probable_title(text), expected)

    def test_explicit_any_visa(self):
        from app.understanding.parsers.contact import extract_work_authorization
        self.assertEqual(extract_work_authorization('ANY VISA!!'), 'Any Visa')
        self.assertEqual(extract_work_authorization('All visa types OK.'), 'Any Visa')

    def test_body_heading_and_blank_table_fields(self):
        from app.email_parsing.parsers import _extract_heading_title
        self.assertEqual(_extract_heading_title('Wordpress developer\nHamilton, NJ'), 'Wordpress developer')
        self.assertEqual(_extract_heading_title('Job Title\n\nUX Designer\nJob Type\nContract'), 'UX Designer')
        self.assertIsNone(_extract_heading_title('Job Title\n\nLocation:\nExample, NJ'))

    def test_screening_steps_are_not_positions(self):
        text = 'Job Title: Data Engineer\nSkills: Python SQL\nNext steps:\n1) Assessment Test\n2) Facial Biometric'
        self.assertEqual(len(_split_requirement_sections(text)), 1)

    def test_signature_role_is_not_position(self):
        text = 'Role: Data Engineer\nSkills: Python SQL\nThanks & Regards,\nAlex Sample\nRole:Technical Recruiter'
        self.assertEqual(len(_split_requirement_sections(text)), 1)

    def test_mode_label_is_not_position(self):
        text = 'Role: Data Center Technician L2\nPosition: Onsite\nLocation: Example, CA\nSkills: Networking'
        self.assertEqual(len(_split_requirement_sections(text)), 1)

    def test_descriptive_role_is_not_position(self):
        text = 'Position: Senior QA Engineer\nSkills: Java\nRole: Hands-on QA Engineer covering both functional testing and automation, with ownership of the regression framework and infrastructure.'
        self.assertEqual(len(_split_requirement_sections(text)), 1)

    def test_real_multiple_jobs_remain_separate(self):
        for text in ['Role: Data Engineer\nSkills: SQL\nRole: Java Developer\nSkills: Java', '1) Data Engineer\nSkills: SQL\n2) Java Developer\nSkills: Java']:
            self.assertEqual(len(_split_requirement_sections(text)), 2)
