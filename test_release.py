"""Release tests use synthetic or retained fixtures, never invented live data."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
import btc_release as r
from btc_validation.core import IntegrityError
NOW=pd.Timestamp('2026-09-05T01:00:00Z')
META={'health':'PARTIAL','run_url':'test','code_sha':'test','preclose_status':'test'}
class ReleaseTests(unittest.TestCase):
    def test_macro_delta_and_actual_period(self):
        d=r.fred_with_change('(DGS2)\n2026-09-03: 4.0\n2026-09-02: 4.1','DGS2',NOW)
        self.assertAlmostEqual(d['change_previous'],-.1);self.assertEqual(d['previous_date'],'2026-09-02')
    def test_macro_missing_change_not_fabricated(self):
        self.assertIsNone(r.fred_with_change('(DGS2)\n2026-09-03: 4.0','DGS2',NOW)['change_previous'])
    def test_original_conflict_guard_preserved(self):
        with self.assertRaises(IntegrityError):r.fred_with_change('(DGS2)\n2026-09-03: 4.0\n2026-09-03: 5.0','DGS2',NOW)
    def test_no_early_macro_packet(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'packet.csv'
            s=r.capture_at_contract_time({},pd.Timestamp('2026-09-07T22:29:59Z'),p)
            self.assertEqual(s,'NOT_IN_MONDAY_CAPTURE_WINDOW');self.assertFalse(p.exists())
    def test_fallback_after_original_capture(self):
        with patch.object(r,'BASE_CAPTURE',return_value='FALLBACK') as f:
            self.assertEqual(r.capture_at_contract_time({},pd.Timestamp('2026-09-07T22:30:00Z')),'FALLBACK')
            f.assert_called_once()
    def test_render_retains_six_columns_and_failure_state(self):
        rows=r.render({},NOW,META)
        self.assertTrue(all(len(x)==6 for x in rows));self.assertEqual(rows[4][2],'ABSTAIN')
        self.assertTrue(any(x[2]=='НЕТ ДАННЫХ' for x in rows if x[0]=='Сценарии'))
    def test_ranges_follow_data_not_previous_report(self):
        f={'spot':{'status':'OK','price':100.,'change_24h_pct':0,'low_24h':90,'high_24h':110},'price_context':{'status':'OK','ma50':100,'ma200':99,'rv20':.5,'low_20d':80.,'high_20d':120.}}
        a=r.render(f,NOW,META);f['price_context']['high_20d']=130
        b=r.render(f,NOW,META)
        self.assertIn('120',next(x[2] for x in a if x[1].startswith('SECONDARY')))
        self.assertIn('130',next(x[2] for x in b if x[1].startswith('SECONDARY')))
    def test_no_probability_or_promoted_claim(self):
        rows=r.render({},NOW,META)
        self.assertEqual(rows[4][2],'ABSTAIN');self.assertFalse(any('p(up)=' in str(x) for x in rows))
    def test_release_ledger_append_is_idempotent(self):
        import json
        with TemporaryDirectory() as tmp:
            ledger=Path(tmp)/'ledger.md';ledger.write_text('old failed experiments\n')
            evidence=Path(tmp)/'e.json';evidence.write_text(json.dumps({'ledger_marker':'unique-marker','ledger_entry':'unique-marker: no promotion'}))
            r.record_release(ledger,evidence);first=ledger.read_bytes();r.record_release(ledger,evidence)
            self.assertEqual(first,ledger.read_bytes());self.assertTrue(ledger.read_text().startswith('old failed experiments\n'))
if __name__=='__main__':unittest.main()
