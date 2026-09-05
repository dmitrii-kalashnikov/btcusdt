"""Paired historical diagnostics. Previously inspected history is consumed.
No hyperparameter selection, promotion or user-facing probabilities.
"""
from __future__ import annotations
import argparse,io,json,math,zipfile
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge,LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import brier_score_loss,log_loss,balanced_accuracy_score,precision_score,recall_score
import btc_baseline as base
from .core import IntegrityError,digest,validate_daily,metrics,pair_predictions,paired_block_interval,nonoverlap_indices,origin_hash
from .runtime import check_runtime_contract,timing_audit

def read_zip_csv(path,name):
    with zipfile.ZipFile(path) as z:return pd.read_csv(io.BytesIO(z.read(name)))

def strict_json(obj):
    def clean(x):
        if isinstance(x,dict):return {k:clean(v) for k,v in x.items()}
        if isinstance(x,(list,tuple)):return [clean(v) for v in x]
        if isinstance(x,np.integer):return int(x)
        if isinstance(x,(np.floating,float)):return float(x) if np.isfinite(x) else None
        if isinstance(x,(pd.Timestamp,datetime)):return x.isoformat()
        return x
    return json.dumps(clean(obj),indent=2,allow_nan=False)

def features_and_events(daily,cfg):
    d=base.add_features_targets(validate_daily(daily))
    for h in cfg['horizons_days']:
        lows=pd.concat([d.low.shift(-k) for k in range(1,h+1)],axis=1);highs=pd.concat([d.high.shift(-k) for k in range(1,h+1)],axis=1)
        complete=lows.notna().all(axis=1)&highs.notna().all(axis=1)
        d[f'mae_path_{h}']=lows.min(axis=1)/d.close-1;d[f'mfe_path_{h}']=highs.max(axis=1)/d.close-1
        d[f'event_{h}']=(d[f'mae_path_{h}']<=float(cfg['risk_thresholds'][str(h)])).astype(float).where(complete)
    return d

def rows_to_metrics(pred):
    rows=[]
    for (split,h,model),g in pred.groupby(['split','horizon','model']):
        g=g.sort_values('time');rows.append({'split':split,'horizon':int(h),'model':model,**metrics(g.prediction,g.actual,origin_vol=g.origin_vol),'nonoverlap_n':len(nonoverlap_indices(g.time,int(h))),'first_origin':str(g.time.min().date()),'last_origin':str(g.time.max().date()),'origin_set_sha256':origin_hash(g.time)})
    return pd.DataFrame(rows)

def compare(pred,candidate,comparator):
    comparisons=[]
    for (split,h),g in pred.groupby(['split','horizon']):
        a=g[g.model==comparator][['time','prediction','actual']];b=g[g.model==candidate][['time','prediction','actual']]
        if a.empty or b.empty:continue
        pair,cov=pair_predictions(a,b)
        if pair.empty:continue
        bm,cm=metrics(pair.prediction_base,pair.actual_base),metrics(pair.prediction_candidate,pair.actual_candidate)
        comparisons.append({'split':split,'horizon':int(h),'candidate':candidate,'comparator':comparator,**cov,'baseline_mae':bm['mae'],'candidate_mae':cm['mae'],'mae_change_pct':100*(cm['mae']/bm['mae']-1) if bm['mae'] else None,'nonoverlap_n':len(nonoverlap_indices(pair.time,int(h))),'uncertainty':paired_block_interval(pair,int(h))})
    return comparisons

def macro_research(daily,cfg):
    d=features_and_events(daily,cfg);seed=pd.read_csv('shadow/seed_macro_weekly_features.csv');seed['forecast_time']=pd.to_datetime(seed.forecast_time,utc=True)
    for col in [x for x in seed if x.endswith('__observation_time')]:
        obs=pd.to_datetime(seed[col],utc=True)
        if (obs>seed.forecast_time).any():raise IntegrityError('Future seed macro observation')
    if seed.forecast_time.duplicated().any():raise IntegrityError('Duplicate seed origin')
    pf,mf=cfg['price_features'],cfg['macro_features']
    f=d.merge(seed[['forecast_time']+mf],left_on='time',right_on='forecast_time',validate='one_to_one').sort_values('time').reset_index(drop=True)
    rows=[];risk=[]
    for split,start,end in [('validation_selection_safe',cfg['validation_start'],cfg['validation_end']),('consumed_secondary',cfg['secondary_start'],cfg['secondary_end'])]:
        start,end=pd.Timestamp(start,tz='UTC'),pd.Timestamp(end,tz='UTC')
        for h in cfg['horizons_days']:
            origins=f[(f.time>=start)&(f.time+pd.Timedelta(days=h)<=end)]
            for i,cur in origins.iterrows():
                t=cur.time;target=f'fwd_ret_{h}d'
                train=f[(f.time+pd.Timedelta(days=h)<=t)&f[target].notna()].dropna(subset=pf+mf+[f'event_{h}'])
                if len(train)<cfg['minimum_training_rows'] or cur[pf+mf].isna().any():continue
                y=train[target].to_numpy(float);pair={}
                for name,cols in [('compact_price_ridge',pf),('compact_price_macro_ridge',pf+mf)]:
                    m=make_pipeline(StandardScaler(),Ridge(alpha=cfg['ridge_alpha']));m.fit(train[cols],y);pair[name]=float(m.predict(f.loc[[i],cols])[0])
                daily_i=int(d.index[d.time==t][0]);frozen=base._predict_one(d,daily_i,h)
                pair.update({'zero_return':0.,'constant_mean':float(y.mean()),'momentum':frozen['momentum'],'four_year_cycle':frozen['four_year_cycle'],'frozen_equal_weight':frozen['equal_weight_ensemble']})
                for name,pred in pair.items():rows.append({'split':split,'time':t,'horizon':h,'model':name,'prediction':pred,'actual':float(cur[target]),'origin_vol':float(cur.rv_30d)*math.sqrt(h/365),'train_n':len(train),'mae_path':float(cur[f'mae_path_{h}']),'mfe_path':float(cur[f'mfe_path_{h}']),'trend_regime':'UP' if cur.ret_90d>0 else 'DOWN','vol_regime':'HIGH' if cur.rv_30d>train.rv_30d.median() else 'LOW'})
                event=train[f'event_{h}'].astype(int);ps={'unconditional_event_frequency':float(event.mean())}
                for name,cols in [('price_logistic',pf),('price_macro_logistic',pf+mf)]:
                    if event.nunique()<2:ps[name]=float(event.mean())
                    else:
                        model=make_pipeline(StandardScaler(),LogisticRegression(C=cfg['logistic_C'],max_iter=1000,class_weight=None));model.fit(train[cols],event);ps[name]=float(model.predict_proba(f.loc[[i],cols])[0,1])
                for name,p in ps.items():risk.append({'split':split,'time':t,'horizon':h,'model':name,'probability':p,'actual_event':int(cur[f'event_{h}']),'train_n':len(train),'threshold':cfg['risk_thresholds'][str(h)],'quality':'EXPERIMENTAL_UNCALIBRATED_NOT_USER_FACING'})
    return pd.DataFrame(rows),pd.DataFrame(risk)

def risk_metrics(risk):
    rows=[];reliability=[]
    for (split,h,m),g in risk.groupby(['split','horizon','model']):
        y,p=g.actual_event.to_numpy(int),g.probability.to_numpy(float)
        rows.append({'split':split,'horizon':int(h),'model':m,'n':len(g),'event_n':int(y.sum()),'brier':float(brier_score_loss(y,p)),'log_loss':float(log_loss(y,np.clip(p,1e-12,1-1e-12),labels=[0,1])),'balanced_accuracy':float(balanced_accuracy_score(y,p>=.5)) if len(np.unique(y))==2 else None,'precision_at_0_5':float(precision_score(y,p>=.5,zero_division=0)),'recall_at_0_5':float(recall_score(y,p>=.5,zero_division=0)),'nonoverlap_n':len(nonoverlap_indices(g.sort_values('time').time,int(h))),'origin_set_sha256':origin_hash(g.sort_values('time').time)})
        for j in range(5):
            mask=(p>=j/5)&((p<(j+1)/5) if j<4 else (p<=1))
            if mask.any():reliability.append({'split':split,'horizon':int(h),'model':m,'bin':j,'n':int(mask.sum()),'mean_prediction':float(p[mask].mean()),'observed_frequency':float(y[mask].mean()),'interpretation':'DIAGNOSTIC_NOT_CALIBRATION_APPROVAL'})
    return pd.DataFrame(rows),pd.DataFrame(reliability)

def baseline_replay(path):
    p=read_zip_csv(path,'artifacts/predictions.csv');p['time']=pd.to_datetime(p.time,utc=True);p=p.rename(columns={'horizon_days':'horizon','prediction_log_return':'prediction','actual_log_return':'actual'})
    z=p[p.model=='constant_mean'].copy();z['model']='zero_return';z['prediction']=0.;q=pd.concat([p,z],ignore_index=True)
    return compare(q,'equal_weight_ensemble','zero_return')

def legacy_derivatives_coverage(path):
    d=read_zip_csv(path,'daily_features.csv');d['time']=pd.to_datetime(d.time,utc=True);cols=[x for x in d if x not in ('time','close')];rows=[]
    for year,g in d.groupby(d.time.dt.year):
        good=g[cols].notna().all(axis=1);rows.append({'year':int(year),'rows':len(g),'all_derivatives_complete':int(good.sum()),'first_complete_date':str(g.loc[good,'time'].min().date()) if good.any() else None,'missing_by_feature':g[cols].isna().sum().to_dict()})
    return rows

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--baseline',required=True);ap.add_argument('--derivatives',required=True);ap.add_argument('--out',default='validation_artifacts');args=ap.parse_args()
    check_runtime_contract();cfg=json.loads(Path('btc_validation/RESEARCH_FREEZE_v1.json').read_text())
    if cfg['promotion_allowed'] is not False or cfg['hyperparameter_search'] is not False:raise IntegrityError('Unregistered promotion/tuning')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    daily=read_zip_csv(args.baseline,'artifacts/btc_daily.csv');daily['time']=pd.to_datetime(daily.time,utc=True);daily=validate_daily(daily)
    if daily.time.max()>pd.Timestamp(cfg['history_last_date'],tz='UTC'):raise IntegrityError('History beyond preregistered cutoff')
    provenance={'baseline_zip_sha256':digest(Path(args.baseline).read_bytes()),'derivatives_zip_sha256':digest(Path(args.derivatives).read_bytes()),'research_manifest_canonical_sha256':digest(json.dumps(cfg,sort_keys=True,separators=(',',':')).encode()),'btc_rows':len(daily),'first_date':str(daily.time.min().date()),'last_date':str(daily.time.max().date())}
    coverage=legacy_derivatives_coverage(args.derivatives)
    (out/'input_coverage.json').write_text(strict_json({'provenance':provenance,'legacy_derivatives':coverage}))
    pred,risk=macro_research(daily,cfg)
    if pred.empty or risk.empty:raise IntegrityError('No eligible origins')
    pred.to_csv(out/'paired_predictions.csv',index=False);risk.to_csv(out/'risk_predictions.csv',index=False)
    ms=rows_to_metrics(pred);ms.to_csv(out/'paired_metrics.csv',index=False);rm,rel=risk_metrics(risk);rm.to_csv(out/'risk_metrics.csv',index=False);rel.to_csv(out/'risk_reliability.csv',index=False)
    sub=[]
    for (split,h,m),g in pred.groupby(['split','horizon','model']):
        for col in ['trend_regime','vol_regime']:
            for regime,x in g.groupby(col):sub.append({'split':split,'horizon':int(h),'model':m,'regime_family':col,'regime':regime,**metrics(x.prediction,x.actual)})
    pd.DataFrame(sub).to_csv(out/'subperiod_metrics.csv',index=False);comparisons=[]
    for benchmark in ['zero_return','constant_mean','momentum','four_year_cycle','frozen_equal_weight','compact_price_ridge']:comparisons+=compare(pred,'compact_price_macro_ridge',benchmark)
    summary={'experiment_id':cfg['experiment_id'],'status':'COMPLETED_DIAGNOSTIC_NOT_PROMOTED','executed_at_utc':datetime.now(timezone.utc).isoformat(),'provenance':provenance,'historical_status':'ALL_INSPECTED_HISTORY_CONSUMED_NO_UNSEEN_CLAIM','promotion_allowed':False,'auto_promoted':False,'user_probabilities':False,'registered_attempts':cfg['regressors']+cfg['risk_classifiers'],'deferred_candidates':{'derivative_families':'See separately executed corrected raw collector and derivative_summary.json; legacy features are not pristine data'},'legacy_baseline_vs_zero_return':baseline_replay(args.baseline),'paired_macro_comparisons':comparisons,'risk_metrics':rm.to_dict('records'),'legacy_issuance_audit':timing_audit(pd.read_csv('shadow/forecasts.csv')),'uncertainty':'Block CIs diagnostic, not multiple-testing-adjusted; nonoverlap not guaranteed independence.'}
    (out/'summary.json').write_text(strict_json(summary));print(ms.to_string(index=False));print(rm.to_string(index=False))

if __name__=='__main__':main()
