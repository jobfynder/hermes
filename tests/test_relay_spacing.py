import unittest
from app.email_parsing.signature import parse_email_signature

class RelaySpacingTests(unittest.TestCase):
    def test_blank_lines_in_relay_header(self):
        for gap in ['\n','\n\n','\n \n\n']:
            text='Subject: Data Engineer\n\nYou received this email via a relay\n'+gap.join(['From:','Alex Sample,','Example Staffing','alex@example.com'])+'\nReply to: alex@example.com\n\nJob Title: Data Engineer\nRequired Skills: SQL\nKeywords: footer'
            parsed=parse_email_signature(text,sender_email='alex@example.com')
            self.assertEqual(parsed['contact']['company_name']['value'],'Example Staffing')
            self.assertEqual(parsed['contact']['full_name']['value'],'Alex Sample')
            self.assertEqual(parsed['method'],'relay_from_block')

    def test_missing_company_does_not_swallow_job_body(self):
        parsed=parse_email_signature('From:\n\nAlex Sample,\n\nalex@example.com\n\nJob Title: Data Engineer\nSkills: SQL',sender_email='alex@example.com')
        self.assertNotEqual(parsed.get('method'),'relay_from_block')
