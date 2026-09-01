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

ROOT=Path('shadow'); FORECAST=ROOT/'forecasts.csv'; SCORE=ROOT/'scorecard.csv'; PROMO=ROOT/'promotion_status.json'; LAST=ROOT/'last_run.json'
def load_csv(p): return pd.read_csv(p) if p.exists() and p.stat().st_size else pd.DataFrame()

def main():
    ROOT.mkdir(exist_ok=True); cfg=src.load_freeze(); capture=datetime.now(timezone.utc).isoformat(); seed=pd.read_csv(src.SEED_PATH); seed['forecast_time']=pd.to_datetime(seed.forecast_time,utc=True)
    daily=download_with_daily_tail(); px=base.add_features_targets(daily); origin=pd.Timestamp(px.time.iloc[-1]).tz_convert('UTC').normalize()
    if origin<src.TRAIN_CUTOFF: raise RuntimeError('BTC source behind frozen cutoff')
    f=load_csv(FORECAST); snap=src.load_preclose(); old=json.loads(PROMO.read_text()) if PROMO.exists() else {'status':'INSUFFICIENT_DATA'}; old_status=old.get('status','INSUFFICIENT_DATA')
    if not snap.empty:
        latest_packet=pd.to_datetime(snap.origin_date,utc=True,errors='raise').max().normalize()
        if latest_packet>origin:
            raise RuntimeError(f'BTC source behind latest pre-close packet: btc_origin={origin.date()} packet_origin={latest_packet.date()}')
    os=origin.strftime('%Y-%m-%d'); new=f.empty or not ((f.origin_date.astype(str).str[:10]==os)&(f.model=='price_ridge')).any(); verified=0; source_status='EXISTING_FROZEN_ORIGIN'
    if new:
        raw=src.preclose_packet(snap,origin); macro=src.current_macro_features(seed,snap,origin,raw); verified=len(src.SERIES); source_status='PRECLOSE_PACKET_PASS'; f=append_origin(f,px,seed,macro,origin,capture)
    f=mature(f,daily); f.to_csv(FORECAST,index=False); sc=scorecard(f); sc.to_csv(SCORE,index=False); pr=promotion(sc,old_status); PROMO.write_text(json.dumps(pr,indent=2,sort_keys=True))
    last={'experiment_id':cfg['experiment_id'],'run_capture_utc':capture,'origin_date':os,'btc_latest_close':float(px.close.iloc[-1]),'new_forecast_origin_appended':bool(new),'macro_source_status':source_status,'macro_series_verified':verified,'macro_feature_count':len(src.MACRO_FEATURES),'promotion_status':pr['status'],'forecast_rows_total':len(f),'completed_rows_total':int((f.status=='COMPLETE').sum()),'governance':'shadow-only; no auto-promotion'}; LAST.write_text(json.dumps(last,indent=2,sort_keys=True)); print(json.dumps(last,indent=2,sort_keys=True))
if __name__=='__main__': main()
