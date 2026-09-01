from __future__ import annotations
import math
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
import btc_baseline as base
from shadow_sources import TRAIN_CUTOFF,PRICE_FEATURES,MACRO_FEATURES

HORIZONS=(7,30,90,180,365); ALPHA=50.0

def ridge(): return Pipeline([('imputer',SimpleImputer(strategy='median')),('scaler',StandardScaler()),('ridge',Ridge(alpha=ALPHA))])
def p_up(mu,sigma): return 0.5 if not np.isfinite(sigma) or sigma<=1e-12 else 0.5*(1+math.erf((mu/sigma)/math.sqrt(2)))

def train_frame(px:pd.DataFrame,seed:pd.DataFrame)->pd.DataFrame:
    p=px[px.time<=TRAIN_CUTOFF].set_index('time'); m=seed.copy(); m['forecast_time']=pd.to_datetime(m.forecast_time,utc=True); m=m[m.forecast_time<=TRAIN_CUTOFF].set_index('forecast_time'); common=p.index.intersection(m.index)
    if len(common)<350: raise RuntimeError(f'Insufficient frozen weekly origins {len(common)}')
    return p.loc[common].join(m.loc[common]).reset_index().rename(columns={'index':'time'})

def frozen_predict(tf,current,macro,h,use_macro):
    target=f'fwd_ret_{h}d'; tr=tf[(tf.time<=TRAIN_CUTOFF-pd.Timedelta(days=h))&tf[target].notna()].copy(); cols=PRICE_FEATURES+(MACRO_FEATURES if use_macro else [])
    if len(tr)<100: raise RuntimeError(f'Insufficient frozen rows {h}d')
    x={c:float(current[c]) for c in PRICE_FEATURES}
    if use_macro: x.update({c:float(macro[c]) for c in MACRO_FEATURES})
    mod=ridge(); mod.fit(tr[cols],tr[target]); mu=float(mod.predict(pd.DataFrame([x],columns=cols))[0]); return mu,float(tr[target].std(ddof=1))

def append_origin(forecasts,px,seed,macro,origin,capture):
    os=origin.strftime('%Y-%m-%d')
    if not forecasts.empty and ((forecasts.origin_date.astype(str).str[:10]==os)&(forecasts.model=='price_ridge')).any(): return forecasts
    q=px[px.time==origin]
    if q.empty: raise RuntimeError(f'No BTC row for {os}')
    cur=q.iloc[-1]; spot=float(cur.close); tf=train_frame(px,seed); rows=[]
    for h in HORIZONS:
        for name,flag in [('price_ridge',False),('price_macro_ridge',True)]:
            mu,sig=frozen_predict(tf,cur,macro,h,flag); rows.append({'forecast_id':f'{os}::{h}::{name}','origin_date':os,'capture_time_utc':capture,'spot_date':os,'horizon_days':h,'due_date':(origin+pd.Timedelta(days=h)).strftime('%Y-%m-%d'),'model':name,'spot':spot,'predicted_log_return':mu,'forecast_price':spot*math.exp(mu),'p_up':p_up(mu,sig),'status':'PENDING','actual_price':'','actual_log_return':'','actual_up':'','source':'scheduled_frozen_shadow_v1'})
        pred=base._predict_one(px,int(q.index[-1]),h); sig=float(pred.pop('target_sigma')); mu=float(pred['equal_weight_ensemble']); rows.append({'forecast_id':f'{os}::{h}::primary_equal_weight_ensemble','origin_date':os,'capture_time_utc':capture,'spot_date':os,'horizon_days':h,'due_date':(origin+pd.Timedelta(days=h)).strftime('%Y-%m-%d'),'model':'primary_equal_weight_ensemble','spot':spot,'predicted_log_return':mu,'forecast_price':spot*math.exp(mu),'p_up':base._p_up(mu,sig),'status':'PENDING','actual_price':'','actual_log_return':'','actual_up':'','source':'scheduled_primary_price_cycle_v2'})
    return pd.concat([forecasts,pd.DataFrame(rows)],ignore_index=True)
