"""Collector integration regressions with full parsed archive schemas."""
import unittest
import math
import numpy as np
import pandas as pd
from .collect import assemble,metrics_day,utc_calendar,build_jobs
from .core import parse_archive_csv,IntegrityError

class FullArchiveCollectorTests(unittest.TestCase):
    def inputs(self):
        raw=b'1640995200000,1,2,1,2,10,1641081599999,20,5,6,12,0\n1641081600000,2,3,2,3,10,1641167999999,30,5,6,18,0\n'
        p=parse_archive_csv(raw,'klines')
        f=parse_archive_csv(b'1640995200000,8,0.0001\n1641024000000,8,0.0001\n1641052800000,8,0.0001\n','fundingRate')
        m=[metrics_day(b'create_time,symbol,sum_open_interest,count_long_short_ratio,sum_toptrader_long_short_ratio\n2022-01-01 23:55:00,BTCUSDT,100,1.1,2.1\n',pd.Timestamp('2022-01-01',tz='UTC'))]
        return p,f,m
    def test_full_schema_merge_preserves_calendar_and_missingness(self):
        p,f,m=self.inputs();d=assemble([p],[f],m,'2022-01-01','2022-01-02')
        self.assertEqual(d.time.tolist(),list(pd.date_range('2022-01-01',periods=2,tz='UTC')))
        self.assertEqual(d.close.tolist(),[2,3]);self.assertFalse(d.columns.duplicated().any())
        self.assertAlmostEqual(d.funding_daily.iloc[0],.0001);self.assertTrue(pd.isna(d.funding_daily.iloc[1]))
        self.assertEqual(d.oi_btc.iloc[0],100);self.assertTrue(pd.isna(d.oi_btc.iloc[1]))
    def test_replayed_normalized_csv_schemas(self):
        import io
        p,f,m=self.inputs();p=pd.read_csv(io.StringIO(p.to_csv(index=False)));f=pd.read_csv(io.StringIO(f.to_csv(index=False)))
        p['time']=pd.to_datetime(p.time,utc=True);f['time']=pd.to_datetime(f.time,utc=True)
        d=assemble([p],[f],m,'2022-01-01','2022-01-02');self.assertEqual(len(d),2)
    def test_ambiguous_measurement_column_rejected(self):
        p,f,m=self.inputs();p['oi_btc']=999
        with self.assertRaises(IntegrityError):assemble([p],[f],m,'2022-01-01','2022-01-02')
    def test_missing_calendar_day_kept_not_compressed(self):
        p,f,m=self.inputs();p=p.iloc[[0]]
        d=assemble([p],[f],m,'2022-01-01','2022-01-03')
        self.assertEqual(len(d),3);self.assertEqual(int(d.close.isna().sum()),2)

class CalendarPlanningTests(unittest.TestCase):
    def test_mixed_naive_and_aware_utc_endpoints(self):
        actual=utc_calendar('2020-09-10',pd.Timestamp('2020-09-12',tz='UTC'))
        self.assertEqual(len(actual),3)
        self.assertEqual(str(actual.tz),'UTC')
    def test_main_default_job_planning_full_period(self):
        jobs=build_jobs(pd.Timestamp('2020-09-01',tz='UTC'),pd.Timestamp('2026-08-31',tz='UTC'))
        self.assertEqual(len([j for j in jobs if j[0]=='klines']),72)
        metrics=[j for j in jobs if j[0]=='metrics']
        self.assertEqual(metrics[0][1],pd.Timestamp('2020-09-10',tz='UTC'))
        self.assertEqual(metrics[-1][1],pd.Timestamp('2026-08-31',tz='UTC'))
        self.assertEqual(len({j[2] for j in jobs}),len(jobs))
    def test_assemble_mixed_bounds(self):
        p,f,m=FullArchiveCollectorTests().inputs()
        d=assemble([p],[f],m,'2022-01-01',pd.Timestamp('2022-01-02',tz='UTC'))
        self.assertEqual(len(d),2)
    def test_invalid_calendar_bounds(self):
        for a,b in [('NaT','2022-01-01'),('2022-01-02','2022-01-01'),('2022-01-01 01:00','2022-01-02')]:
            with self.assertRaises(IntegrityError):utc_calendar(a,b)

if __name__=='__main__':unittest.main()
