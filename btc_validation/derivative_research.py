"""Separate OI/funding, positioning and taker ablations on corrected raw data."""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from .core import IntegrityError,validate_daily
from .replay import read_zip_csv,features_and_events,rows_to_metrics,compare,strict_json

def run(daily,deriv,cfg):
    daily=features_and_events(daily,cfg)
    if deriv.time.duplicated().any():raise IntegrityError('Duplicate derivative dates')
    cols=sum(cfg['derivative_families'].values(),[]);d=daily.merge(deriv[['time']+cols],on='time',how='left',validate='one_to_one');validate_daily(d);rows=[];status=[];pf=cfg['price_features'];anchor=pd.Timestamp(cfg['origin_anchor'],tz='UTC');grid=(d.time-anchor).dt.days%cfg['forecast_origin_stride_days']==0
    for family,extra in cfg['derivative_families'].items():
        for split,a,b in [('validation_selection_safe',cfg['validation_start'],cfg['validation_end']),('consumed_secondary',cfg['secondary_start'],cfg['secondary_end'])]:
            for h in cfg['horizons_days']:
                a,b=pd.to_datetime(a,utc=True),pd.to_datetime(b,utc=True);origins=d[grid&(d.time>=a)&(d.time+pd.Timedelta(days=h)<=b)];used=0
                for i,cur in origins.iterrows():
                    target=f'fwd_ret_{h}d';train=d[(d.time+pd.Timedelta(days=h)<=cur.time)&d[target].notna()].dropna(subset=pf+extra)
                    if len(train)<cfg['minimum_training_rows'] or cur[pf+extra].isna().any():continue
                    for name,features in [(f'price_on_{family}_rows',pf),(f'compact_price_{family}_ridge',pf+extra)]:
                        model=make_pipeline(StandardScaler(),Ridge(alpha=cfg['ridge_alpha']));model.fit(train[features],train[target]);pred=float(model.predict(d.loc[[i],features])[0]);rows.append({'split':split,'time':cur.time,'horizon':h,'model':name,'prediction':pred,'actual':float(cur[target]),'origin_vol':float(cur.rv_30d)*math.sqrt(h/365),'train_n':len(train)})
                    used+=1
                status.append({'family':family,'split':split,'horizon':h,'scheduled_origins':len(origins),'paired_origins':used,'skipped_for_history_or_coverage':len(origins)-used})
    return pd.DataFrame(rows),status

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--baseline',required=True);ap.add_argument('--data',required=True);ap.add_argument('--out',default='validation_artifacts');args=ap.parse_args();cfg=json.loads(Path('btc_validation/RESEARCH_FREEZE_v1.json').read_text());source_status=json.loads((Path(args.data).parent/'coverage.json').read_text())
    if source_status['source_failures']:raise IntegrityError('Unresolved raw source failure')
    daily=read_zip_csv(args.baseline,'artifacts/btc_daily.csv');daily['time']=pd.to_datetime(daily.time,utc=True);deriv=pd.read_csv(args.data);deriv['time']=pd.to_datetime(deriv.time,utc=True);out=Path(args.out);out.mkdir(exist_ok=True,parents=True);pred,status=run(daily,deriv,cfg)
    if pred.empty:raise IntegrityError('No derivatives diagnostic outcomes')
    pred.to_csv(out/'derivative_predictions.csv',index=False);ms=rows_to_metrics(pred);ms.to_csv(out/'derivative_metrics.csv',index=False);comparisons=[]
    for family in cfg['derivative_families']:comparisons+=compare(pred,f'compact_price_{family}_ridge',f'price_on_{family}_rows')
    result={'experiment_id':cfg['experiment_id'],'status':'COMPLETED_DIAGNOSTIC_ONLY','source_quality':source_status,'coverage':status,'comparisons':comparisons,'promotion_allowed':False,'auto_promoted':False,'holdout_status':'2024-2025 CONSUMED, NOT AN UNSEEN TEST'}
    (out/'derivative_summary.json').write_text(strict_json(result));print(ms.to_string(index=False))

if __name__=='__main__':main()
