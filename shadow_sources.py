from __future__ import annotations
import hashlib, io, json, math, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import requests
import btc_baseline as base

ROOT=Path('shadow'); FREEZE_PATH=ROOT/'SHADOW_FREEZE_v1.json'; SEED_PATH=ROOT/'seed_macro_weekly_features.csv'
TRAIN_CUTOFF=pd.Timestamp('2026-08-31',tz='UTC'); ALFRED='https://alfred.stlouisfed.org/graph/alfredgraph.csv'
SERIES={'M2SL':'m2','WALCL':'fed_assets','WTREGEN':'tga','RRPONTSYD':'rrp','DFF':'fed_funds','DGS2':'ust_2y','DGS10':'ust_10y','DFII10':'real_10y','DTWEXBGS':'broad_usd','VIXCLS':'vix','NASDAQCOM':'nasdaq','CPIAUCSL':'cpi','UNRATE':'unemployment','PAYEMS':'payrolls'}
GROWTH=('broad_usd','m2','payrolls','nasdaq','cpi','tga','fed_assets')
LEVEL=('rrp','ust_10y','unemployment','fed_funds','ust_2y','real_10y','vix')
PRICE_FEATURES=list(base.FEATURES)
MACRO_FEATURES=[]
for n in GROWTH: MACRO_FEATURES += [f'{n}_logchg_13w',f'{n}_logchg_52w']
for n in LEVEL: MACRO_FEATURES += [n,f'{n}_delta_13w',f'{n}_delta_52w']
MACRO_FEATURES += ['yield_curve_10y_2y','breakeven_proxy_10y','net_liquidity_logchg_13w','net_liquidity_logchg_52w']

def sha256(b:bytes)->str: return hashlib.sha256(b).hexdigest()

def load_freeze()->dict:
    c=json.loads(FREEZE_PATH.read_text())
    checks=[c.get('experiment_id')=='btc-shadow-prospective-v1',c.get('training_cutoff')=='2026-08-31',c.get('macro_feature_count')==len(MACRO_FEATURES),c.get('governance',{}).get('no_auto_promotion') is True]
    if not all(checks): raise RuntimeError('Shadow contract drift')
    if sha256(SEED_PATH.read_bytes())!=c.get('seed_macro_weekly_features_sha256'): raise RuntimeError('Seed macro SHA256 mismatch')
    return c

def fetch_one(sid:str,vintage:pd.Timestamp,s:requests.Session)->dict:
    v=pd.Timestamp(vintage); v=v.tz_convert('UTC') if v.tzinfo else v.tz_localize('UTC'); vd=v.strftime('%Y-%m-%d')
    # Only the last known print is needed here. 13w/52w lags come from the frozen PIT seed,
    # so a compact exact-vintage window avoids expensive ALFRED history rendering.
    q={'id':sid,'vintage_date':vd,'cosd':(v-pd.Timedelta(days=120)).strftime('%Y-%m-%d'),'coed':vd}
    raw=None; last_error=None
    for attempt in range(1,5):
        try:
            print(f'ALFRED {sid} vintage={vd} attempt={attempt}',flush=True)
            r=s.get(ALFRED,params=q,timeout=(15,35))
            r.raise_for_status(); raw=r.content
            break
        except requests.RequestException as e:
            last_error=f'{type(e).__name__}: {e}'
            if attempt<4: time.sleep(2**attempt)
    if raw is None: raise RuntimeError(f'ALFRED transport failed after 4 attempts for {sid} vintage={vd}; last={last_error}')
    d=pd.read_csv(io.BytesIO(raw))
    if d.shape[1]<2: raise RuntimeError(f'ALFRED schema failure {sid}')
    dates=pd.to_datetime(d.iloc[:,0],utc=True,errors='coerce'); vals=pd.to_numeric(d.iloc[:,1].replace('.',pd.NA),errors='coerce')
    ok=dates.notna()&vals.notna()&(dates<=v.normalize())
    if not ok.any(): raise RuntimeError(f'No ALFRED value {sid} vintage {vd}')
    j=dates[ok].idxmax()
    return {'series_id':sid,'name':SERIES[sid],'value':float(vals.loc[j]),'observation_date':dates.loc[j].strftime('%Y-%m-%d'),'vintage_date':vd,'source_sha256':sha256(raw)}

def fetch_vintage(origin:pd.Timestamp)->tuple[dict,list[dict]]:
    s=requests.Session(); s.headers.update({'User-Agent':'btc-shadow-prospective/1.2','Accept':'text/csv'}); wide={}; rows=[]; capture=datetime.now(timezone.utc).isoformat()
    for sid in SERIES:
        r=fetch_one(sid,origin,s); wide[r['name']]=r['value']; rows.append({'origin_date':pd.Timestamp(origin).strftime('%Y-%m-%d'),'capture_time_utc':capture,'series_id':sid,'value':r['value'],'observation_date':r['observation_date'],'source_sha256':r['source_sha256'],'vintage_date':r['vintage_date']})
    return wide,rows

def raw_history(seed:pd.DataFrame,snap:pd.DataFrame)->pd.DataFrame:
    names=list(SERIES.values()); a=seed[['forecast_time']+names].copy().rename(columns={'forecast_time':'origin_date'}); a['origin_date']=pd.to_datetime(a['origin_date'],utc=True).dt.normalize()
    if snap.empty: return a.sort_values('origin_date').drop_duplicates('origin_date',keep='last')
    p=snap.pivot_table(index='origin_date',columns='series_id',values='value',aggfunc='last').reset_index(); p['origin_date']=pd.to_datetime(p['origin_date'],utc=True).dt.normalize(); p=p.rename(columns=SERIES)
    for c in names:
        if c not in p: p[c]=np.nan
    return pd.concat([a,p[['origin_date']+names]],ignore_index=True).sort_values('origin_date').drop_duplicates('origin_date',keep='last')

def current_macro_features(seed:pd.DataFrame,snap:pd.DataFrame,origin:pd.Timestamp,cur:dict)->dict:
    h=raw_history(seed,snap); t=pd.Timestamp(origin).normalize(); h=pd.concat([h,pd.DataFrame([{'origin_date':t}|cur])],ignore_index=True).sort_values('origin_date').drop_duplicates('origin_date',keep='last').set_index('origin_date')
    a,b=t-pd.Timedelta(days=91),t-pd.Timedelta(days=364)
    if a not in h.index or b not in h.index: raise RuntimeError(f'Missing 13w/52w lag origin {a.date()} / {b.date()}')
    o={}
    for n in GROWTH:
        x,x13,x52=map(float,(h.at[t,n],h.at[a,n],h.at[b,n]))
        if min(x,x13,x52)<=0: raise RuntimeError(f'Non-positive growth level {n}')
        o[f'{n}_logchg_13w']=math.log(x/x13); o[f'{n}_logchg_52w']=math.log(x/x52)
    for n in LEVEL:
        x,x13,x52=map(float,(h.at[t,n],h.at[a,n],h.at[b,n])); o[n]=x; o[f'{n}_delta_13w']=x-x13; o[f'{n}_delta_52w']=x-x52
    o['yield_curve_10y_2y']=float(h.at[t,'ust_10y']-h.at[t,'ust_2y']); o['breakeven_proxy_10y']=float(h.at[t,'ust_10y']-h.at[t,'real_10y'])
    nl=lambda d: float(h.at[d,'fed_assets']-h.at[d,'tga']-1000*h.at[d,'rrp']); x,x13,x52=nl(t),nl(a),nl(b)
    if min(x,x13,x52)<=0: raise RuntimeError('Non-positive net liquidity')
    o['net_liquidity_logchg_13w']=math.log(x/x13); o['net_liquidity_logchg_52w']=math.log(x/x52)
    if any(c not in o or not np.isfinite(o[c]) for c in MACRO_FEATURES): raise RuntimeError('Incomplete macro feature vector')
    return o
