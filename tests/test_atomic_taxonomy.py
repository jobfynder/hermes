import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app.understanding.taxonomy.loader import _write_json_atomic
from app.email_parsing.parsers import parse_requirement_email
class AtomicTaxonomyTests(unittest.TestCase):
 def test_replacement_failure_preserves_original(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'taxonomy.json';path.write_text('{"old":true}')
   with patch('app.understanding.taxonomy.loader.os.replace',side_effect=OSError('synthetic')):
    with self.assertRaises(OSError):_write_json_atomic(path,{'new':True})
   self.assertEqual(json.loads(path.read_text()),{'old':True})
   self.assertEqual(list(Path(folder).iterdir()),[path])
 def test_replacement_publishes_complete_document(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'taxonomy.json';path.write_text('{}')
   _write_json_atomic(path,{'skills':['Python','SQL']})
   self.assertEqual(json.loads(path.read_text()),{'skills':['Python','SQL']})
 def test_numbered_position_with_separate_title_splits(self):
  parsed=parse_requirement_email('Position: 1\n\nTitle: Java Developer\nCompany: Example\nRequired Skills: Java\n\nPosition: 2\n\nTitle: Data Engineer\nCompany: Example\nRequired Skills: SQL')
  self.assertEqual([r['job_title'] for r in parsed['records']],['Java Developer','Data Engineer'])
