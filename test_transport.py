"""Source transport regression fixtures, not live market measurements."""
import unittest
import pandas as pd
import btc_transport as t
from btc_validation.core import IntegrityError
NOW=pd.Timestamp('2026-09-05T01:00:00Z')
class TransportTests(unittest.TestCase):
    def test_daily_fred_table(self):
        text='Title: Rate (DFII10)\n| 2026-09-03: | 2.4200 |\n| 2026-09-02: | 2.45 |'
        d=t.parse_fred_page(text,'DFII10',NOW)
        self.assertEqual(d['value'],'2.4200');self.assertEqual(d['observation_date'],'2026-09-03')
    def test_monthly_fred_table(self):
        d=t.parse_fred_page('M2 (M2SL)\n| Jul 2026: | 23,218.0 |','M2SL',NOW)
        self.assertEqual(d['value'],'23218.0');self.assertEqual(d['observation_date'],'2026-07-01')
    def test_duplicate_identical_observation_allowed(self):
        d=t.parse_fred_page('(WALCL)\n2026-09-02: 6,737,204 | units\n| 2026-09-02: | 6,737,204 |','WALCL',NOW)
        self.assertEqual(d['value'],'6737204')
    def test_conflicting_observations_fail(self):
        with self.assertRaises(IntegrityError):t.parse_fred_page('(WALCL)\n2026-09-02: 1\n2026-09-02: 2','WALCL',NOW)
    def test_wrong_fred_series_fail(self):
        with self.assertRaises(IntegrityError):t.parse_fred_page('(M2SL)\n2026-09-02: 1','WALCL',NOW)
    def test_no_observation_fails(self):
        with self.assertRaises(IntegrityError):t.parse_fred_page('(WALCL)\nUnavailable','WALCL',NOW)
    def test_future_observation_fails(self):
        with self.assertRaises(IntegrityError):t.parse_fred_page('(WALCL)\n2026-09-06: 1','WALCL',NOW)
    def test_etf_source_cell_roundtrip(self):
        a='| 03 Sep 2026 | '+' | '.join(['1']*12+['12'])+' |\n'
        b='| 04 Sep 2026 | '+' | '.join(['-']+['0']*12)+' |'
        d=t.parse_etf_page(a+b,NOW)
        self.assertEqual(d['latest']['total_usdm'],12);self.assertEqual(d['latest']['date'],'2026-09-03')
    def test_etf_unknown_schema_fails(self):
        with self.assertRaises(IntegrityError):t.parse_etf_page('| 03 Sep 2026 | 1 |',NOW)
    def test_reader_denies_arbitrary_url(self):
        with self.assertRaises(IntegrityError):t.reader('https://example.com/')
    def test_funding_restriction_not_routed_around(self):
        with self.assertRaisesRegex(IntegrityError,'451'):t.funding_unavailable()
if __name__=='__main__':unittest.main()
