"""Frozen weekly shadow plus integrity overlay and separate post-publication evidence."""
from __future__ import annotations
import json
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd
import btc_baseline as base
from run_baseline_fresh import download_with_daily_tail
import shadow_sources as src
from shadow_model import append_origin
from shadow_score import mature,scorecard,promotion
from btc_validation.core import IntegrityError,validate_daily
from btc_validation.runtime import expected_monday,validate_forecasts,assert_forecasts_immutable,timing_audit
ROOT=Path('shadow');FORECAST=ROOT/'forecasts.csv';SCORE=ROOT/'scorecard.csv';PROMO=ROOT/'promotion_status.json';LAST=ROOT/'last_run.json'

def load_csv(p):return pd.read_csv(p) if p.exists() and p.stat().st_size else pd.DataFrame()
def atomic_text(path,text):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(text);tmp.replace(path)

def main():
    ROOT.mkdir(exist_ok=True);cfg=src.load_freeze()
    seed=pd.read_csv(src.SEED_PATH);seed['forecast_time']=pd.to_datetime(seed.forecast_time,utc=True)
    daily=validate_daily(download_with_daily_tail());now=pd.Timestamp.now(tz='UTC')
    daily=daily[daily.time+pd.Timedelta(days=1)<=now].reset_index(drop=True);origin=expected_monday(now)
    if origin<src.TRAIN_CUTOFF or daily.empty or daily.time.max()<origin:raise IntegrityError('BTC archive behind required closed weekly origin')
    px=base.add_features_targets(daily);f=load_csv(FORECAST);validate_forecasts(f);original=f.copy(deep=True);snap=src.load_preclose()
    if not snap.empty:
        src.raw_history(seed,snap)
        if pd.to_datetime(snap.origin_date,utc=True).max()>origin:raise IntegrityError('Packet newer than required closed weekly origin')
    old=json.loads(PROMO.read_text()) if PROMO.exists() else {'status':'INSUFFICIENT_DATA'}
    os=origin.strftime('%Y-%m-%d');new=f.empty or os not in set(f.origin_date.astype(str));verified=0;source_status='EXISTING_FROZEN_ORIGIN'
    if new:
        previous=origin-pd.Timedelta(days=7)
        if previous>=src.TRAIN_CUTOFF and (f.empty or previous.strftime('%Y-%m-%d') not in set(f.origin_date)):raise IntegrityError('Missed weekly origin; no retroactive prospective backfill')
        raw=src.preclose_packet(snap,origin);macro=src.current_macro_features(seed,snap,origin,raw)
        f=append_origin(f,px,seed,macro,origin,datetime.now(timezone.utc).isoformat())
        f.loc[f.origin_date.astype(str)==os,'capture_time_utc']=datetime.now(timezone.utc).isoformat()
        verified=len(src.SERIES);source_status='PRECLOSE_PACKET_PASS'
    from btc_validation.issued import load_records,append_issued,PATH as ISSUED_PATH,save_state
    issued_records=load_records()
    if new:issued_records=append_issued(issued_records,f,origin)
    f=mature(f,daily);assert_forecasts_immutable(original,f);sc=scorecard(f);pr=promotion(sc,old.get('status','INSUFFICIENT_DATA'));audit=timing_audit(f)
    capture=datetime.now(timezone.utc).isoformat()
    last={'experiment_id':cfg['experiment_id'],'integrity_overlay':'btc-integrity-v1-20260904','run_capture_utc':capture,'origin_date':os,'data_as_of_utc':(origin+pd.Timedelta(days=1)).isoformat(),'btc_latest_close':float(px.loc[px.time==origin,'close'].iloc[0]),'archive_latest_date':str(daily.time.max().date()),'new_forecast_origin_appended':bool(new),'macro_source_status':source_status,'macro_series_verified':verified,'macro_feature_count':len(src.MACRO_FEATURES),'promotion_status':pr['status'],'forecast_rows_total':len(f),'completed_rows_total':int((f.status=='COMPLETE').sum()),'issuance_audit':audit,'governance':'shadow-only; no auto-promotion'}
    if not f.equals(original):atomic_text(FORECAST,f.to_csv(index=False))
    atomic_text(SCORE,sc.to_csv(index=False));atomic_text(PROMO,json.dumps(pr,indent=2,sort_keys=True));atomic_text(LAST,json.dumps(last,indent=2,sort_keys=True))
    if new:atomic_text(ISSUED_PATH,''.join(json.dumps(x,sort_keys=True,separators=(',',':'))+'\n' for x in issued_records))
    issued_status=save_state(issued_records);print(json.dumps(last,indent=2,sort_keys=True))
    if issued_status['evidence_failures']:raise IntegrityError('Issued forecast evidence failure; no promotion permitted')

if __name__=='__main__':main()
