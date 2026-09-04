from __future__ import annotations

import io, json, math, zipfile, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

BASE='https://data.binance.vision/data/futures/um'
SYMBOL='BTCUSDT'
OUT=Path('derivatives_artifacts'); OUT.mkdir(exist_ok=True)
HORIZONS=(7,30,90)
ALPHA=50.0


def get_zip(url, timeout=30):
    r=requests.get(url,timeout=timeout,headers={'User-Agent':'btc-forecast-lab/0.4'})
    if r.status_code==404: return None
    r.raise_for_status(); raw=r.content
    c=requests.get(url+'.CHECKSUM',timeout=15,headers={'User-Agent':'btc-forecast-lab/0.4'})
    if c.status_code==200:
        exp=c.text.strip().split()[0].lower(); got=hashlib.sha256(raw).hexdigest()
        if exp!=got: raise RuntimeError(f'checksum mismatch {url}')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.endswith('.csv')]
        if len(names)!=1: raise RuntimeError(url)
        return z.read(names[0])


def read_csv_bytes(b, header='infer'):
    return pd.read_csv(io.BytesIO(b),header=header)


def daterange(a,b):
    d=a
    while d<=b:
        yield d; d+=timedelta(days=1)


def download_metrics():
    start=date(2020,9,10); end=date(2026,8,31)
    days=list(daterange(start,end))
    def one(d):
        url=f'{BASE}/daily/metrics/{SYMBOL}/{SYMBOL}-metrics-{d.isoformat()}.zip'
        try:
            raw=get_zip(url)
            if raw is None: return None
            df=read_csv_bytes(raw)
            if df.empty:return None
            df['source_date']=d.isoformat(); return df
        except Exception as e:
            return None
    parts=[]
    with ThreadPoolExecutor(max_workers=24) as ex:
        futs=[ex.submit(one,d) for d in days]
        for f in as_completed(futs):
            x=f.result()
            if x is not None: parts.append(x)
    if not parts: raise RuntimeError('no metrics')
    m=pd.concat(parts,ignore_index=True)
    # Archive metrics are 5m snapshots. Aggregate to daily using last snapshot for state ratios/OI.
    m['time']=pd.to_datetime(m['create_time'],utc=True,errors='coerce')
    for c in m.columns:
        if c not in ('create_time','symbol','source_date','time'): m[c]=pd.to_numeric(m[c],errors='coerce')
    m=m.sort_values('time').dropna(subset=['time'])
    daily=m.groupby(m.time.dt.floor('D')).last(numeric_only=False)
    # `time` is both retained by groupby-last and used as the grouped index; drop the retained copy before reset_index.
    daily=daily.drop(columns=['time'],errors='ignore')
    daily.index.name='time'; daily=daily.reset_index()
    return daily


def month_iter(a,b):
    y,m=a.year,a.month
    while (y,m)<=(b.year,b.month):
        yield y,m
        m+=1
        if m==13:y+=1;m=1


def download_monthly(kind, interval=None, start=date(2020,9,1), end=date(2026,8,31)):
    parts=[]
    for y,m in month_iter(start,end):
        if kind=='fundingRate':
            url=f'{BASE}/monthly/fundingRate/{SYMBOL}/{SYMBOL}-fundingRate-{y:04d}-{m:02d}.zip'
        else:
            url=f'{BASE}/monthly/klines/{SYMBOL}/{interval}/{SYMBOL}-{interval}-{y:04d}-{m:02d}.zip'
        raw=get_zip(url)
        if raw is None: continue
        try: df=read_csv_bytes(raw)
        except: df=read_csv_bytes(raw,header=None)
        parts.append(df)
    if not parts: raise RuntimeError(f'no {kind}')
    return pd.concat(parts,ignore_index=True)


def normalize_price():
    df=download_monthly('klines','1d')
    # Futures archive may be headered or not.
    if 'open_time' not in df.columns:
        cols=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','taker_buy_base','taker_buy_quote','ignore']
        df=df.iloc[:,:len(cols)]; df.columns=cols
    df['time']=pd.to_datetime(pd.to_numeric(df['open_time'],errors='coerce'),unit='ms',utc=True,errors='coerce').dt.floor('D')
    df['close']=pd.to_numeric(df['close'],errors='coerce')
    return df[['time','close']].dropna().drop_duplicates('time').sort_values('time')


def normalize_funding():
    f=download_monthly('fundingRate')
    cols={str(c).lower():c for c in f.columns}
    tcol=next((cols[x] for x in cols if 'time' in x or 'calc' in x),None)
    rcol=next((cols[x] for x in cols if 'funding' in x and 'rate' in x),None)
    if tcol is None or rcol is None:
        # fallback known monthly layout: calc_time,funding_interval_hours,last_funding_rate
        if len(f.columns)>=3:
            tcol=f.columns[0]; rcol=f.columns[-1]
        else: raise RuntimeError(f'unknown funding cols {list(f.columns)}')
    tv=f[tcol]
    if pd.api.types.is_numeric_dtype(tv): tm=pd.to_datetime(tv,unit='ms',utc=True,errors='coerce')
    else: tm=pd.to_datetime(tv,utc=True,errors='coerce')
    rate=pd.to_numeric(f[rcol],errors='coerce')
    x=pd.DataFrame({'time':tm.dt.floor('D'),'funding':rate}).dropna()
    return x.groupby('time',as_index=False).funding.mean().sort_values('time')


def build():
    p=normalize_price(); m=download_metrics(); f=normalize_funding()
    d=p.merge(m,on='time',how='inner').merge(f,on='time',how='left').sort_values('time').reset_index(drop=True)
    d['funding']=d['funding'].fillna(0.0)
    oi='sum_open_interest_value' if 'sum_open_interest_value' in d.columns else 'sum_open_interest'
    ratio_cols=[c for c in ['count_toptrader_long_short_ratio','sum_toptrader_long_short_ratio','count_long_short_ratio','sum_taker_long_short_vol_ratio'] if c in d.columns]
    d['logp']=np.log(d.close)
    for n in (1,7,30,90): d[f'ret_{n}']=d.logp.diff(n)
    d['rv30']=d.logp.diff().rolling(30).std()*math.sqrt(365)
    d['oi_log']=np.log(pd.to_numeric(d[oi],errors='coerce').replace(0,np.nan))
    for n in (1,7,30): d[f'oi_chg_{n}']=d.oi_log.diff(n)
    for n in (1,7,30): d[f'funding_mean_{n}']=d.funding.rolling(n).mean()
    for c in ratio_cols:
        d[c]=pd.to_numeric(d[c],errors='coerce')
        d[f'{c}_z90']=(d[c]-d[c].rolling(90).mean())/d[c].rolling(90).std()
    d['funding_z90']=(d.funding_mean_7-d.funding_mean_7.rolling(90).mean())/d.funding_mean_7.rolling(90).std()
    for h in HORIZONS:d[f'y_{h}']=d.logp.shift(-h)-d.logp
    price_feats=['ret_7','ret_30','ret_90','rv30']
    deriv_feats=['oi_chg_1','oi_chg_7','oi_chg_30','funding_mean_1','funding_mean_7','funding_mean_30','funding_z90']+[f'{c}_z90' for c in ratio_cols]
    return d,price_feats,deriv_feats


def fit_predict(d, feats, h, start, end):
    rows=[]
    mask=(d.time>=pd.Timestamp(start,tz='UTC'))&(d.time<=pd.Timestamp(end,tz='UTC'))
    idx=d.index[mask].tolist()[::7]
    for i in idx:
        if pd.isna(d.at[i,f'y_{h}']):continue
        # Strict PIT label realization: only train on origins whose h-day target is known at forecast time.
        train=d.iloc[:max(0,i-h+1)].dropna(subset=feats+[f'y_{h}'])
        if len(train)<180 or d.loc[i,feats].isna().any():continue
        model=Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=ALPHA))])
        model.fit(train[feats],train[f'y_{h}'])
        pred=float(model.predict(d.loc[[i],feats])[0])
        rows.append((d.at[i,'time'],pred,float(d.at[i,f'y_{h}'])))
    return rows


def score(rows):
    a=np.array([x[2] for x in rows]); p=np.array([x[1] for x in rows])
    return {'n':len(rows),'mae':float(np.mean(np.abs(p-a))),'rmse':float(np.sqrt(np.mean((p-a)**2))),'direction':float(np.mean(np.sign(p)==np.sign(a)))}


def event_study(d):
    # Fixed, non-optimized crowding definition: positive 30d price and OI trend + funding/taker crowding above rolling 90d mean.
    tak='sum_taker_long_short_vol_ratio_z90'
    top='sum_toptrader_long_short_ratio_z90'
    sig=(d.ret_30>0)&(d.oi_chg_30>0)&(d.funding_z90>0)
    if top in d:sig &= d[top]>0
    if tak in d:sig &= d[tak]<0  # weak aggressive-buy flow despite rising price/OI
    rows=[]
    for h in HORIZONS:
        y=d[f'y_{h}']; s=y[sig & y.notna()]; b=y[(~sig)&y.notna()]
        rows.append({'horizon':h,'signal_n':int(len(s)),'signal_mean':float(s.mean()),'signal_median':float(s.median()),'signal_down_rate':float((s<0).mean()) if len(s) else None,'background_mean':float(b.mean()),'background_down_rate':float((b<0).mean())})
    return rows


def main():
    d,pf,df=build(); allf=pf+df
    out=[]
    for split,a,b in [('validation_2022_2023','2022-01-01','2023-12-31'),('diagnostic_2024_2025','2024-01-01','2025-12-31'),('post_2026_ytd','2026-01-01','2026-08-31')]:
        for h in HORIZONS:
            base=fit_predict(d,pf,h,a,b); ext=fit_predict(d,allf,h,a,b)
            sb,se=score(base),score(ext)
            out.append({'split':split,'horizon':h,'price_only':sb,'price_plus_derivatives':se,'mae_change_pct':100*(se['mae']/sb['mae']-1)})
    ev=event_study(d)
    summary={'experiment':'btc-derivatives-pit-v1','data_start':str(d.time.min()),'data_end':str(d.time.max()),'rows':len(d),'features_price':pf,'features_derivatives':df,'ridge_alpha_fixed':ALPHA,'no_leakage':'expanding train ends at i-h; all features backward-looking','model_results':out,'crowding_event_study':ev}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2,default=str))
    d[['time','close']+df].to_csv(OUT/'daily_features.csv',index=False)
    pd.json_normalize(out).to_csv(OUT/'model_results.csv',index=False)
    pd.DataFrame(ev).to_csv(OUT/'crowding_event_study.csv',index=False)
    print(json.dumps(summary,indent=2,default=str))

if __name__=='__main__':main()
