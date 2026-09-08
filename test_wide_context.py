import tempfile, json, unittest
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
import btc_wide_context as w
NOW=datetime(2026,9,8,17,30,tzinfo=timezone.utc)
class WideContextTests(unittest.TestCase):
 def test_exact_schema(self):
  self.assertEqual(w.parse_history('observation_date,SOFR\n2026-09-04,3.65\n','SOFR',NOW),[(date(2026,9,4),3.65)])
 def test_wrong_series(self):
  with self.assertRaises(ValueError):w.parse_history('DATE,IORB\n2026-09-04,3.65','SOFR',NOW)
 def test_duplicate(self):
  with self.assertRaises(ValueError):w.parse_history('DATE,SOFR\n2026-09-04,3\n2026-09-04,3','SOFR',NOW)
 def test_future(self):
  with self.assertRaises(ValueError):w.parse_history('DATE,SOFR\n2026-09-09,3','SOFR',NOW)
 def test_nonfinite(self):
  with self.assertRaises(ValueError):w.parse_history('DATE,SOFR\n2026-09-04,NaN','SOFR',NOW)
 def test_stale(self):
  with self.assertRaises(ValueError):w.parse_history('DATE,SOFR\n2026-08-01,3','SOFR',NOW)
 def test_missing_not_zero(self):
  h=w.parse_history('DATE,SOFR\n2026-09-03,.\n2026-09-04,3.65','SOFR',NOW)
  self.assertEqual(len(h),1)
  self.assertIsNone(w.summarize(h)['change_previous'])
 def test_unordered(self):
  with self.assertRaises(ValueError):w.parse_history('DATE,SOFR\n2026-09-04,3\n2026-09-03,3','SOFR',NOW)
 def test_paired_dates(self):
  a=[(date(2026,9,4),3.65)];b=[(date(2026,9,4),3.65),(date(2026,9,8),3.7)]
  self.assertAlmostEqual(w.aligned_rate_spread(a,b,NOW)['basis_points'],0)
 def test_no_pair(self):
  with self.assertRaises(ValueError):w.aligned_rate_spread([(date(2026,9,4),1)],[(date(2026,9,8),2)],NOW)
 def test_z_excludes_current(self):
  h=[(date(2026,6,1)+timedelta(days=i),float(i)) for i in range(61)]
  s=w.summarize(h)
  import statistics
  self.assertAlmostEqual(s['z_prior_60_observations'],(60-29.5)/statistics.stdev(range(60)))
 def test_insufficient_z(self):
  self.assertIsNone(w.summarize([(date(2026,9,4),1)])['z_prior_60_observations'])
 def test_no_fake_direction(self):
  rows=w.report_rows({}, {'events':[]}, NOW)
  self.assertTrue(all(len(r)==6 for r in rows))
  self.assertFalse(any('купить' in r[2].lower() for r in rows))
  self.assertEqual(rows[0][2],'НЕТ ДАННЫХ')
 def test_no_vintage_claim(self):
  class Response:text='URL Source: https://fred.stlouisfed.org/series/SOFR\nRate (SOFR)\n2026-09-04: 3.65\n'
  def get(url):
   if not url.endswith('/SOFR'):raise RuntimeError('Unavailable fixture')
   return Response()
  d=w.collect(NOW,get,lambda r,t:{'observed_at_utc':t})
  self.assertEqual(d['SOFR']['vintage_policy'],'CURRENT_VINTAGE_CONTEXT_ONLY_NOT_HISTORICAL_PIT')
  self.assertEqual(d['IORB']['status'],'UNAVAILABLE')
 def test_institution_availability(self):
  packet={'schema':'institution-context-v1','decision_weight':0,'events':[{
   'source_url':'https://www.sec.gov/Archives/edgar/data/1050446/test',
   'observed_by_agent_utc':NOW.isoformat(),'period_end':'2026-09-07','filing_date':'2026-09-08'}]}
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'event.json';p.write_text(json.dumps(packet));r=w.read_institution_packet(p,NOW)
   self.assertEqual(r['events'][0]['available_at_utc'],NOW.isoformat())
 def test_page_identity(self):
  with self.assertRaises(ValueError):w.parse_page('URL Source: wrong\n(SOFR)\n2026-09-04: 3.65','SOFR',NOW)
 def test_page_access_restriction(self):
  with self.assertRaises(ValueError):w.parse_page('URL Source: https://fred.stlouisfed.org/series/SOFR\n(SOFR)\nWarning: 403 error\n2026-09-04: 3.65','SOFR',NOW)
 def test_institution_future_filing(self):
  packet={'schema':'institution-context-v1','decision_weight':0,'events':[{
   'source_url':'https://www.sec.gov/Archives/edgar/data/1050446/test',
   'observed_by_agent_utc':NOW.isoformat(),'period_end':'2026-09-07','filing_date':'2026-09-09'}]}
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'event.json';p.write_text(json.dumps(packet))
   with self.assertRaises(ValueError):w.read_institution_packet(p,NOW)
 def test_missing_rows_cannot_hide_unordered_calendar(self):
  with self.assertRaises(ValueError):w.parse_history('DATE,SOFR\n2026-09-04,.\n2026-09-03,3.65','SOFR',NOW)
 def test_frozen_packet_membership_not_touched(self):
  self.assertEqual(len(w.SERIES),9)
  self.assertNotIn('M2SL',w.SERIES)
if __name__=='__main__':unittest.main()
