"""Executed adversarial regression tests. Synthetic fixtures are NOT market evidence."""
from __future__ import annotations
import io,json,math,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import shadow_sources as sources
import shadow_score as scorer
from . import core as c
from . import runtime as r

def packet():
    rows=[]
    for sid in sources.SERIES:
        value='100.00';url=f'https://fred.stlouisfed.org/series/{sid}'
        rows.append({'origin_date':'2026-09-07','capture_time_utc':'2026-09-07T22:30:00Z','target_btc_close_time_utc':'2026-09-08T00:00:00Z','series_id':sid,'value':value,'observation_date':'2026-09-01','source_sha256':c.observation_hash(sid,'2026-09-01',value,url),'source_url':url})
    return pd.DataFrame(rows)

def forecasts(origin='2026-08-31',complete=False):
    t=c.day(origin);rows=[]
    for h in r.HORIZONS:
        for m in r.MODELS:
            actual=.01;rows.append({'forecast_id':f'{origin}::{h}::{m}','origin_date':origin,'capture_time_utc':(t+pd.Timedelta(days=1,hours=9)).isoformat(),'spot_date':origin,'horizon_days':h,'due_date':str((t+pd.Timedelta(days=h)).date()),'model':m,'spot':100.,'predicted_log_return':.02,'forecast_price':100*math.exp(.02),'p_up':.55,'status':'COMPLETE' if complete else 'PENDING','actual_price':100*math.exp(actual) if complete else '','actual_log_return':actual if complete else '','actual_up':1. if complete else '','source':'synthetic_fixture'})
    return pd.DataFrame(rows)

def predictions(dates=('2022-01-03','2022-01-10')):
    return pd.DataFrame({'time':[pd.Timestamp(x,tz='UTC') for x in dates],'prediction':[.01]*len(dates),'actual':[.02]*len(dates)})

class PacketTests(unittest.TestCase):
    def verify(self,p):return c.validate_packet(p,pd.Timestamp('2026-09-07',tz='UTC'),sources.SERIES,now='2026-09-07T23:00:00Z')
    def test_valid_packet(self):self.assertEqual(len(self.verify(packet())),14)
    def test_bad_hash_rejected(self):
        p=packet();p.loc[0,'source_sha256']='0'*64
        with self.assertRaises(c.IntegrityError):self.verify(p)
    def test_wrong_url_rejected(self):
        p=packet();p.loc[0,'source_url']='https://evil.invalid/M2SL'
        with self.assertRaises(c.IntegrityError):self.verify(p)
    def test_future_observation_rejected(self):
        p=packet();p.loc[0,'observation_date']='2026-09-08'
        with self.assertRaises(c.IntegrityError):self.verify(p)
    def test_wrong_target_close_rejected(self):
        p=packet();p['target_btc_close_time_utc']='2026-09-09T00:00:00Z'
        with self.assertRaises(c.IntegrityError):self.verify(p)
    def test_late_capture_rejected(self):
        p=packet();p['capture_time_utc']='2026-09-08T00:00:01Z'
        with self.assertRaises(c.IntegrityError):self.verify(p)
    def test_future_capture_rejected(self):
        p=packet();p['capture_time_utc']='2026-09-07T23:30:00Z'
        with self.assertRaises(c.IntegrityError):self.verify(p)
    def test_duplicate_series_rejected(self):
        p=packet();p.loc[0]=p.loc[1]
        with self.assertRaises(c.IntegrityError):self.verify(p)
    def test_missing_series_rejected(self):
        with self.assertRaises(c.IntegrityError):self.verify(packet().iloc[:-1])
    def test_nonfinite_value_rejected(self):
        p=packet();p.loc[0,'value']='NaN'
        with self.assertRaises(c.IntegrityError):self.verify(p)
    def test_naive_timestamp_rejected(self):
        p=packet();p.loc[0,'capture_time_utc']='2026-09-07 22:30:00'
        with self.assertRaises(c.IntegrityError):self.verify(p)
    def test_date_truncation_not_allowed(self):
        p=packet();p.loc[0,'origin_date']='2026-09-07FAKE'
        with self.assertRaises(c.IntegrityError):self.verify(p)
    def test_decimal_csv_roundtrip(self):
        p=pd.read_csv(io.StringIO(packet().to_csv(index=False)),dtype=str,keep_default_na=False)
        self.assertEqual(self.verify(p)['m2'],100.)
    def test_production_packet_wrapper(self):
        with patch('btc_validation.core.pd.Timestamp.now',return_value=pd.Timestamp('2026-09-07T23:00:00Z')):self.assertEqual(len(sources.preclose_packet(packet(),pd.Timestamp('2026-09-07',tz='UTC'))),14)

class ForecastTests(unittest.TestCase):
    def test_valid_forecasts(self):r.validate_forecasts(forecasts())
    def test_duplicate_forecast_rejected(self):
        f=forecasts()
        with self.assertRaises(c.IntegrityError):r.validate_forecasts(pd.concat([f,f.iloc[:1]]))
    def test_partial_origin_rejected(self):
        with self.assertRaises(c.IntegrityError):r.validate_forecasts(forecasts().iloc[:1])
    def test_wrong_due_date_rejected(self):
        f=forecasts();f.loc[0,'due_date']='2026-09-08'
        with self.assertRaises(c.IntegrityError):r.validate_forecasts(f)
    def test_inference_before_data_rejected(self):
        f=forecasts();f.loc[0,'capture_time_utc']='2026-08-31T23:00:00Z'
        with self.assertRaises(c.IntegrityError):r.validate_forecasts(f)
    def test_post_outcome_backfill_rejected(self):
        f=forecasts();f.loc[0,'capture_time_utc']='2026-10-01T00:00:00Z'
        with self.assertRaises(c.IntegrityError):r.validate_forecasts(f)
    def test_price_return_parity_rejected(self):
        f=forecasts();f.loc[0,'forecast_price']=500
        with self.assertRaises(c.IntegrityError):r.validate_forecasts(f)
    def test_completed_actual_parity_rejected(self):
        f=forecasts(complete=True);f.loc[0,'actual_up']=0
        with self.assertRaises(c.IntegrityError):r.validate_forecasts(f)
    def test_immutable_forecast_rewrite_rejected(self):
        f=forecasts();g=f.copy();g.loc[0,'p_up']=.7
        with self.assertRaises(c.IntegrityError):r.assert_forecasts_immutable(f,g)
    def test_pending_to_complete_allowed(self):r.assert_forecasts_immutable(forecasts(),forecasts(complete=True))
    def test_duplicate_not_counted_as_evidence(self):
        f=forecasts(complete=True)
        with self.assertRaises(c.IntegrityError):scorer.scorecard(pd.concat([f]*26))
    def test_unpaired_completed_origins_rejected(self):
        f=forecasts(complete=True).iloc[1:]
        with self.assertRaises(c.IntegrityError):scorer.scorecard(f)
    def test_delayed_anchors_not_prospective(self):
        f=forecasts(complete=True);audit=r.timing_audit(f);self.assertEqual(audit['eligible_prospective_rows'],0);self.assertEqual(audit['delayed_origin_rows'],15);s=scorer.scorecard(f);self.assertTrue((s.eligible_prospective_n==0).all())
    def test_promotion_requires_pair_proof(self):
        s=scorer.scorecard(forecasts(complete=True));s.loc[s.model=='price_ridge','n']=1;s.loc[s.model=='price_macro_ridge','n']=26
        with self.assertRaises(c.IntegrityError):scorer.promotion(s,'INSUFFICIENT_DATA')
    def test_promotion_hash_mismatch_rejected(self):
        s=scorer.scorecard(forecasts(complete=True));s.loc[0,'origin_set_sha256']='bad'
        with self.assertRaises(c.IntegrityError):scorer.promotion(s,'INSUFFICIENT_DATA')
    def test_delayed_gate_stays_closed(self):
        s=scorer.scorecard(forecasts(complete=True));p=scorer.promotion(s,'WATCH_POSITIVE');self.assertFalse(p['auto_promoted']);self.assertEqual(p['status'],'INSUFFICIENT_DATA')
    def test_expected_monday_not_latest_random_day(self):
        self.assertEqual(str(r.expected_monday('2026-09-04T22:00:00Z').date()),'2026-08-31');self.assertEqual(str(r.expected_monday('2026-09-07T22:00:00Z').date()),'2026-08-31');self.assertEqual(str(r.expected_monday('2026-09-08T09:15:00Z').date()),'2026-09-07')

class HistoricalTests(unittest.TestCase):
    def test_exact_pairing_discloses_coverage(self):
        pair,cov=c.pair_predictions(predictions(),predictions(('2022-01-10','2022-01-17')));self.assertEqual(len(pair),1);self.assertEqual(cov['baseline_excluded'],1)
    def test_strict_pairing_rejects_different_dates(self):
        with self.assertRaises(c.IntegrityError):c.pair_predictions(predictions(),predictions(('2022-01-10',)),strict=True)
    def test_pairing_rejects_different_actuals(self):
        a=predictions();b=a.copy();b.loc[0,'actual']=.8
        with self.assertRaises(c.IntegrityError):c.pair_predictions(a,b)
    def test_no_future_label_or_release(self):
        origin=pd.date_range('2022-01-01',periods=3,tz='UTC');ends=origin+pd.Timedelta(days=7);available=origin.copy();np.testing.assert_equal(c.eligible_training_mask(origin,ends,available,'2022-01-09T00:00:00Z'),[True,True,False]);available=list(available);available[0]=pd.Timestamp('2022-01-10',tz='UTC');np.testing.assert_equal(c.eligible_training_mask(origin,ends,available,'2022-01-09T00:00:00Z'),[False,True,False])
    def test_validation_does_not_consume_2024_outcomes(self):
        origins=[pd.Timestamp('2023-12-01',tz='UTC'),pd.Timestamp('2023-12-30',tz='UTC')];np.testing.assert_equal(c.validation_labels_mask(origins,30,'2023-12-31T00:00:00Z'),[True,False])
    def test_calendar_gap_rejected(self):
        p=pd.DataFrame({'time':pd.to_datetime(['2022-01-01','2022-01-03'],utc=True),'close':[100,110]})
        with self.assertRaises(c.IntegrityError):c.calendar_targets(p,1)
    def test_calendar_targets_exact(self):
        p=pd.DataFrame({'time':pd.date_range('2022-01-01',periods=4,tz='UTC'),'close':[100,110,121,130]});self.assertAlmostEqual(c.calendar_targets(p,2).iloc[0],math.log(1.21))
    def test_nonoverlap_not_duplicate_dates(self):
        t=pd.date_range('2022-01-03',periods=11,freq='7D',tz='UTC');self.assertEqual(c.nonoverlap_indices(t,30),[0,5,10])
    def test_bootstrap_small_sample_suppressed(self):
        pair,_=c.pair_predictions(predictions(),predictions());self.assertIsNone(c.paired_block_interval(pair,30)['interval_95'])
    def test_metrics_independent_oracle(self):
        m=c.metrics([0.,3.],[1.,1.]);self.assertEqual(m['mae'],1.5);self.assertEqual(m['signed_bias'],.5);self.assertAlmostEqual(m['rmse'],math.sqrt(2.5))
    def test_headerless_first_row_preserved(self):
        x='1640995200000,1,2,1,2,10,1641081599999,20,5,6,12,0\n1641081600000,2,3,2,3,10,1641167999999,30,5,6,18,0\n';d=c.parse_archive_csv(x.encode(),'klines');self.assertEqual(len(d),2);self.assertEqual(d.close.tolist(),[2,3])
    def test_headered_and_headerless_same(self):
        x='1640995200000,1,2,1,2,10,1641081599999,20,5,6,12,0\n';a=c.parse_archive_csv(x.encode(),'klines');b=c.parse_archive_csv((','.join(c.KLINE_COLUMNS)+'\n'+x).encode(),'klines');pd.testing.assert_frame_equal(a,b)
    def test_missing_funding_not_zero(self):
        d=c.parse_archive_csv(b'1640995200000,8,\n1641024000000,8,0\n','fundingRate');self.assertTrue(pd.isna(d.last_funding_rate.iloc[0]));self.assertEqual(d.last_funding_rate.iloc[1],0)
    def test_frozen_contract_content_hash(self):
        r.check_runtime_contract();pins=json.loads(Path('btc_validation/INTEGRITY_CONTRACT_v1.json').read_text())['frozen_file_sha256']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for file in pins:
                p=root/file;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(Path(file).read_bytes())
            (root/'BASELINE_FREEZE_v2.json').write_text('{}')
            with self.assertRaises(c.IntegrityError):c.check_frozen_files(root,pins)

class IssuanceTests(unittest.TestCase):
    def test_future_anchor_is_after_issue(self):
        from .issued import anchor_after
        self.assertEqual(anchor_after('2026-09-08T09:15:00Z'),pd.Timestamp('2026-09-08T10:00:00Z'));self.assertEqual(anchor_after('2026-09-08T09:55:00Z'),pd.Timestamp('2026-09-08T11:00:00Z'))
    def test_append_issued_no_retroactive_target(self):
        from .issued import append_issued
        out=append_issued([],forecasts('2026-09-07'),pd.Timestamp('2026-09-07',tz='UTC'),'2026-09-08T09:15:00Z');self.assertEqual(len(out),15);self.assertEqual(out[0]['period_start_utc'],'2026-09-08T10:00:00+00:00');self.assertEqual(out[0]['period_end_utc'],'2026-09-15T10:00:00+00:00');self.assertEqual(out[0]['decision_weight'],0)
    def test_issued_idempotent(self):
        from .issued import append_issued
        f=forecasts('2026-09-07');origin=pd.Timestamp('2026-09-07',tz='UTC');a=append_issued([],f,origin,'2026-09-08T09:15:00Z');self.assertEqual(append_issued(a,f,origin,'2026-09-08T09:35:00Z'),a)
    def test_issued_record_rewrite_rejected(self):
        from .issued import append_issued,validate_record
        a=append_issued([],forecasts('2026-09-07'),pd.Timestamp('2026-09-07',tz='UTC'),'2026-09-08T09:15:00Z');a[0]['predicted_log_return']=.5
        with self.assertRaises(c.IntegrityError):validate_record(a[0])
    def test_issued_future_outcomes_not_scored(self):
        from .issued import append_issued,evaluate
        a=append_issued([],forecasts('2026-09-07'),pd.Timestamp('2026-09-07',tz='UTC'),'2026-09-08T09:15:00Z')
        def no_price(*args,**kwargs):raise AssertionError('Future price requested')
        result,health=evaluate(a,now='2026-09-09T00:00:00Z',resolve=lambda _: {'commit_sha':'test'},prices=no_price);self.assertTrue(result.empty);self.assertTrue(all(x['status']=='PENDING_OUTCOME' for x in health))
    def test_uncommitted_issued_forecast_not_scored(self):
        from .issued import append_issued,evaluate
        a=append_issued([],forecasts('2026-09-07'),pd.Timestamp('2026-09-07',tz='UTC'),'2026-09-08T09:15:00Z');result,health=evaluate(a,now='2027-09-09T00:00:00Z',resolve=lambda _:None);self.assertTrue(result.empty);self.assertTrue(all(x['status']=='AWAITING_PUBLICATION_PROOF' for x in health))
    def test_actual_return_uses_future_anchor_not_legacy_spot(self):
        from .issued import append_issued,evaluate
        a=append_issued([],forecasts('2026-09-07'),pd.Timestamp('2026-09-07',tz='UTC'),'2026-09-08T09:15:00Z')
        def px(t,now=None):return (200 if '2026-09-08' in t else 220),{'fixture':True}
        result,_=evaluate(a,now='2027-09-09T00:00:00Z',resolve=lambda _: {'commit_sha':'test'},prices=px);self.assertEqual(len(result),15);np.testing.assert_allclose(result.actual,math.log(1.1))

class CollectorTests(unittest.TestCase):
    def test_metrics_last_row_not_columnwise_fill(self):
        from .collect import metrics_day
        raw=b'create_time,symbol,sum_open_interest,count_long_short_ratio,sum_toptrader_long_short_ratio\n2022-01-01 00:00:00,BTCUSDT,100,1.1,2.1\n2022-01-01 23:55:00,BTCUSDT,101,1.2,\n';got=metrics_day(raw,pd.Timestamp('2022-01-01',tz='UTC'));self.assertEqual(got['oi_btc'],101);self.assertTrue(pd.isna(got['top_positions_ls']))
    def test_taker_ratio_is_volume_weighted_and_oi_is_btc(self):
        from .collect import assemble
        times=pd.date_range('2022-01-01',periods=7,tz='UTC');p=pd.DataFrame({'time':times,'close':100.,'quote_volume':[100.,200.,100.,100.,100.,100.,100.],'taker_buy_quote':[100.,0.,50.,50.,50.,50.,50.]});ms=[{'time':t,'oi_btc':100.,'global_accounts_ls':1.,'top_positions_ls':2.} for t in times];d=assemble([p],[],ms,'2022-01-01','2022-01-07');self.assertAlmostEqual(d.taker_imbalance_7d.iloc[-1],-.125);self.assertTrue(d.funding_mean_7d.isna().all());self.assertTrue((d.oi_btc_chg_1d.iloc[1:]==0).all())

class GitPublicationTests(unittest.TestCase):
    def fixture(self,date,callback):
        import os,subprocess
        from .issued import append_issued,PATH,publication_proof,canonical
        a=append_issued([],forecasts('2026-09-07'),pd.Timestamp('2026-09-07',tz='UTC'),'2026-09-08T09:15:00Z')
        with tempfile.TemporaryDirectory() as tmp:
            old=os.getcwd()
            try:
                os.chdir(tmp);subprocess.run(['git','init','-q'],check=True);subprocess.run(['git','config','user.name','synthetic-test'],check=True);subprocess.run(['git','config','user.email','synthetic-test@example.invalid'],check=True);PATH.parent.mkdir(parents=True);PATH.write_text(''.join(json.dumps(x)+'\n' for x in a));subprocess.run(['git','add',str(PATH)],check=True);env=os.environ|{'GIT_AUTHOR_DATE':date,'GIT_COMMITTER_DATE':date};subprocess.run(['git','commit','-qm','synthetic test fixture'],env=env,check=True);callback(a,publication_proof,canonical)
            finally:os.chdir(old)
    def test_real_first_commit_proof(self):
        def check(a,proof,_):self.assertIsNotNone(proof(a[0]))
        self.fixture('2026-09-08T09:20:00Z',check)
    def test_late_first_commit_rejected(self):
        def check(a,proof,_):
            with self.assertRaises(c.IntegrityError):proof(a[0])
        self.fixture('2026-09-08T10:01:00Z',check)
    def test_rehashed_prediction_rewrite_rejected_by_git(self):
        def check(a,proof,canonical):
            a[0]['predicted_log_return']=.7;a[0]['record_sha256']=c.digest(canonical(a[0]).encode())
            with self.assertRaises(c.IntegrityError):proof(a[0])
        self.fixture('2026-09-08T09:20:00Z',check)

if __name__=='__main__':unittest.main()
