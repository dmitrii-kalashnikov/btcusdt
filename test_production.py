"""Deterministic production regressions; fixtures are synthetic, not market evidence."""
import csv, io, math, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import btc_production as p
from btc_validation.core import IntegrityError

NOW=pd.Timestamp('2026-09-05T12:30:00Z')

def candles(interval='1h',n=25):
    step=int(pd.Timedelta(interval).total_seconds()*1000)
    start=int((NOW.floor(interval)-n*pd.Timedelta(interval)).timestamp()*1000)
    return [[start+i*step,'100','110','90','105','10',start+(i+1)*step-1,'1000',5,'6','600','0'] for i in range(n+1)]

def etf_html(rows):
    return '<table><tr>'+''.join('<th>'+x+'</th>' for x in ['']+['F'+str(i) for i in range(12)]+['Total'])+'</tr>'+''.join('<tr>'+''.join('<td>'+str(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</table>'

class ProductionTests(unittest.TestCase):
    def test_open_candle_excluded(self):
        d=p.parse_klines(candles(),'1h',NOW);self.assertEqual(len(d),25)
        self.assertEqual(d.time.iloc[-1],NOW.floor('h')-pd.Timedelta(hours=1))
    def test_candle_gap_rejected(self):
        x=candles();x.pop(4)
        with self.assertRaises(IntegrityError):p.parse_klines(x,'1h',NOW)
    def test_stale_closed_candles_rejected(self):
        with self.assertRaises(IntegrityError):p.parse_klines(candles()[:-2],'1h',NOW)
    def test_impossible_ohlc_rejected(self):
        x=candles();x[0][2]='99'
        with self.assertRaises(IntegrityError):p.parse_klines(x,'1h',NOW)
    def test_impossible_taker_volume_rejected(self):
        x=candles();x[0][10]='1001'
        with self.assertRaises(IntegrityError):p.parse_klines(x,'1h',NOW)
    def test_duplicate_candles_rejected(self):
        x=candles();x.insert(2,x[1])
        with self.assertRaises(IntegrityError):p.parse_klines(x,'1h',NOW)
    def test_bad_boundary_rejected(self):
        x=candles();x[0][6]+=1
        with self.assertRaises(IntegrityError):p.parse_klines(x,'1h',NOW)
    def test_nan_measurement_rejected(self):
        for value in ('NaN','inf','-inf'):
            with self.assertRaises(IntegrityError):p.number(value)
    def test_source_stale_or_future_rejected(self):
        for dt in (NOW-pd.Timedelta(minutes=5),NOW+pd.Timedelta(minutes=5)):
            with self.assertRaises(IntegrityError):p.timely(dt.timestamp()*1000,NOW,180)
    def test_missing_source_is_not_zero(self):
        _,value=p.safe('example',lambda:1/0)
        self.assertEqual(value['status'],'UNAVAILABLE');self.assertNotIn('value',value)
    def test_etf_partial_zero_total_excluded(self):
        rows=[['01 Sep 2026']+[1]*12+[12],['02 Sep 2026']+[2]*12+[24],['03 Sep 2026']+[3]*12+[36],['04 Sep 2026']+['-']+[0]*11+[0]]
        d=p.parse_etf(etf_html(rows),NOW)
        self.assertEqual(d['latest']['date'],'2026-09-03');self.assertEqual(d['sum3_usdm'],72)
        self.assertEqual(d['partial_sessions'],['2026-09-04']);self.assertIsNone(d['sum5_usdm'])
    def test_etf_internal_missing_session_not_compressed(self):
        rows=[['01 Sep 2026']+[1]*12+[12],['02 Sep 2026']+['-']+[0]*11+[0],['03 Sep 2026']+[3]*12+[36]]
        self.assertIsNone(p.parse_etf(etf_html(rows),NOW)['sum3_usdm'])
    def test_etf_total_mismatch_rejected(self):
        with self.assertRaises(IntegrityError):p.parse_etf(etf_html([['03 Sep 2026']+[1]*12+[99]]),NOW)
    def test_etf_parentheses_negative(self):self.assertEqual(p.flow_number('(236.5)'),-236.5)
    def test_etf_absence_not_zero(self):self.assertIsNone(p.flow_number('-'))
    def test_fred_exact_decimal_preserved(self):
        d=p.parse_fred('observation_date,DFII10\n2026-09-03,1.2300\n2026-09-04,.\n','DFII10',NOW)
        self.assertEqual(d['value'],'1.2300');self.assertEqual(d['observation_date'],'2026-09-03')
    def test_fred_wrong_schema_rejected(self):
        with self.assertRaises(IntegrityError):p.parse_fred('DATE,OTHER\n2026-09-03,2\n','DFII10',NOW)
    def test_fred_stale_rejected(self):
        with self.assertRaises(IntegrityError):p.parse_fred('DATE,VIXCLS\n2026-08-01,20\n','VIXCLS',NOW)
    def test_fred_future_rejected(self):
        with self.assertRaises(IntegrityError):p.parse_fred('DATE,VIXCLS\n2026-09-06,20\n','VIXCLS',NOW)
    def test_fred_duplicates_rejected(self):
        with self.assertRaises(IntegrityError):p.parse_fred('DATE,VIXCLS\n2026-09-03,20\n2026-09-03,21\n','VIXCLS',NOW)
    def test_no_retroactive_preclose_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'packets.csv';status=p.capture_preclose({},NOW,path)
            self.assertEqual(status,'NOT_IN_MONDAY_CAPTURE_WINDOW');self.assertFalse(path.exists())
    def test_incomplete_preclose_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'packets.csv';status=p.capture_preclose({},pd.Timestamp('2026-09-07T21:00:00Z'),path)
            self.assertEqual(status,'INCOMPLETE_PACKET_NOT_WRITTEN');self.assertFalse(path.exists())
    def test_complete_preclose_idempotent_and_decimal_safe(self):
        now=pd.Timestamp('2026-09-07T21:00:00Z');feeds={}
        for sid in p.shadow.SERIES:
            feeds['fred_'+sid]={'status':'OK','value':'1.2300','observation_date':'2026-09-04',
                               'source_url':f'https://fred.stlouisfed.org/series/{sid}',
                               'source':{'retrieved_at_utc':'2026-09-07T20:59:00Z'}}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'packets.csv';self.assertEqual(p.capture_preclose(feeds,now,path),'COMPLETE_PACKET_CAPTURED_BEFORE_CLOSE')
            old=path.read_bytes();self.assertEqual(p.capture_preclose(feeds,now,path),'ALREADY_CAPTURED_IMMUTABLE')
            self.assertEqual(old,path.read_bytes());self.assertIn(b'1.2300',old)
    def test_outlook_does_not_expose_probability(self):
        d=p.frozen_outlook();self.assertTrue(d['rows']);self.assertNotIn('p_up',d['rows'][0])
    def test_descriptive_view_needs_both_sources(self):
        self.assertEqual(p.describe({})[0],'НЕДОСТАТОЧНО ДАННЫХ')
    def test_descriptive_divergence(self):
        feeds={'etf':{'status':'OK','sum3_usdm':1},'spot_flow':{'status':'OK','buy_sell_ratio':.9}}
        self.assertEqual(p.describe(feeds)[0],'ПРОТИВОРЕЧИВЫЕ ПОТОКИ')
    def test_volatility_math(self):
        r=p.ranges(100,.5);self.assertAlmostEqual(r[7][0]*r[7][1],10000)
        self.assertTrue(r[90][0]<r[7][0]<100<r[7][1]<r[90][1])
    def test_render_failure_still_exposes_abstain_and_health(self):
        meta={'health':'DATA_FAILURE','run_url':'test','code_sha':'test','preclose_status':'test'}
        rows=p.report_rows({},NOW,meta)
        self.assertEqual(rows[3][2],'DATA_FAILURE');self.assertEqual(rows[4][2],'ABSTAIN')
        self.assertTrue(all(len(x)==6 for x in rows))
        self.assertGreater(rows[1][2],40000)
    def test_csv_roundtrip_and_formula_injection(self):
        data=list(csv.reader(io.StringIO(p.csv_text([['x','a,b','="bad"',12,'a\nb','@cmd']]))))
        self.assertEqual(data[0][1],'a,b');self.assertEqual(data[0][2],'\'="bad"');self.assertEqual(data[0][5],"'@cmd")

if __name__=='__main__':unittest.main()
