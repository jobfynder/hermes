import unittest
from copy import deepcopy
from app.drafts.review_rules import parser_is_ready

class ReviewRulesTests(unittest.TestCase):
    def setUp(self):
        self.row={'draft_type':'draft_hotlist','confidence':0.75,'errors':[],
            'parsing':{'document_kind':'hotlist','confidence':0.75,'requires_review':False,'warnings':[],
                'records':[{'parse_confidence':0.75,'requires_review':False,'warnings':[]}]}}
    def test_complete_parser_output_is_ready(self): self.assertTrue(parser_is_ready(self.row))
    def test_missing_information_is_not_approved(self):
        row=deepcopy(self.row); row['parsing']['records'][0]['warnings']=['candidate_name_missing']
        self.assertFalse(parser_is_ready(row))
    def test_wrong_document_type_is_not_approved(self):
        row=deepcopy(self.row); row['parsing']['document_kind']='unknown'
        self.assertFalse(parser_is_ready(row))
    def test_low_confidence_is_not_approved(self):
        row=deepcopy(self.row); row['confidence']=0.65
        self.assertFalse(parser_is_ready(row))
    def test_intake_error_is_not_approved(self):
        row=deepcopy(self.row); row['errors']=['validation_failed']
        self.assertFalse(parser_is_ready(row))

if __name__=='__main__':unittest.main()
