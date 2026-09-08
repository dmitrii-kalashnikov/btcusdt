import json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import btc_context_runner as runner
from btc_validation.core import IntegrityError

class ContextRunnerTests(unittest.TestCase):
 def setUp(self):
  self.old=os.getcwd();self.tmp=tempfile.TemporaryDirectory();os.chdir(self.tmp.name)
 def tearDown(self):
  os.chdir(self.old);self.tmp.cleanup()
 def state(self,status):
  Path('shadow').mkdir(exist_ok=True)
  Path('shadow/issued_status.json').write_text(json.dumps({'row_status':[{'status':status}]}))
 def test_no_status_no_action(self):
  self.assertIsNone(runner.refresh_pending_publication())
 def test_pending_outcome_does_not_rescore(self):
  self.state('PENDING_OUTCOME')
  with patch('btc_validation.issued.save_state') as save:
   self.assertIsNone(runner.refresh_pending_publication());save.assert_not_called()
 def test_same_records_only(self):
  self.state('AWAITING_PUBLICATION_PROOF');records=[{'sentinel':'unchanged'}]
  result={'evidence_failures':0,'row_status':[{'status':'PENDING_OUTCOME'}]}
  with patch('btc_validation.issued.load_records',return_value=records),patch('btc_validation.issued.save_state',return_value=result) as save,patch('btc_validation.issued.append_issued') as append:
   self.assertEqual(runner.refresh_pending_publication(),result)
   save.assert_called_once_with(records);append.assert_not_called()
 def test_late_publication_never_rescued(self):
  self.state('AWAITING_PUBLICATION_PROOF')
  with patch('btc_validation.issued.load_records',return_value=[]),patch('btc_validation.issued.save_state',return_value={'evidence_failures':1,'row_status':[{'status':'EVIDENCE_FAILURE'}]}):
   with self.assertRaises(IntegrityError):runner.refresh_pending_publication()
 def test_ledger_preserves_failed_history_and_is_idempotent(self):
  Path('research').mkdir();Path('EXPERIMENT_LEDGER.md').write_text('OLD FAILED MODEL\n')
  Path('research/WIDE_CONTEXT_LEDGER_ENTRY.md').write_text('## wide-context-review-20260908\nNo promotion.\n')
  runner.record_review();first=Path('EXPERIMENT_LEDGER.md').read_bytes()
  runner.record_review();self.assertEqual(Path('EXPERIMENT_LEDGER.md').read_bytes(),first)
  self.assertTrue(first.startswith(b'OLD FAILED MODEL\n'))

if __name__=='__main__':unittest.main()
