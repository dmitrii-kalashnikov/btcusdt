"""Shared deterministic integrity primitives. Checks do not confer predictive validity.
A hash fingerprints an observation; it is not proof of remote publication.
"""
from __future__ import annotations
import hashlib, io, json, math, re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable
import numpy as np
import pandas as pd

class IntegrityError(RuntimeError):
    """Fail closed on provenance, calendar, uniqueness or evaluation violations."""

def utc(value):
    t=pd.Timestamp(value)
    if pd.isna(t) or t.tzinfo is None: raise IntegrityError(f'Timestamp must be timezone-aware: {value!r}')
    return t.tz_convert('UTC')

def day(value):
    text=str(value)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',text): raise IntegrityError(f'Expected exact YYYY-MM-DD: {text!r}')
    try: return pd.Timestamp(text,tz='UTC')
    except ValueError as exc: raise IntegrityError('Invalid calendar date') from exc

def digest(data:bytes)->str: return hashlib.sha256(data).hexdigest()

def decimal_text(value):
    try: number=Decimal(str(value))
    except InvalidOperation as exc: raise IntegrityError('Invalid decimal observation') from exc
    if not number.is_finite(): raise IntegrityError('Non-finite observation')
    return format(number,'f')

def observation_hash(series_id,observation_date,value,source_url):
    return digest(f'{series_id}|{observation_date}|{decimal_text(value)}|{source_url}'.encode())

def validate_packet(snap,origin,series,*,now=None):
    t=utc(origin)
    if t!=t.normalize() or t.weekday()!=0: raise IntegrityError('Macro packet origin must be a UTC Monday date')
    required={'origin_date','capture_time_utc','target_btc_close_time_utc','series_id','value','observation_date','source_sha256','source_url'}
    if snap.columns.duplicated().any() or not required.issubset(snap.columns): raise IntegrityError('Missing/duplicate packet columns')
    for v in snap.origin_date: day(v)
    g=snap[snap.origin_date.astype(str)==t.strftime('%Y-%m-%d')]
    if len(g)!=len(series) or set(g.series_id)!=set(series) or g.series_id.duplicated().any(): raise IntegrityError('Exactly one row per required macro series is required')
    expected_close=t+pd.Timedelta(days=1)
    now=utc(now) if now is not None else pd.Timestamp.now(tz='UTC')
    values={}
    for r in g.itertuples(index=False):
        capture,target=utc(r.capture_time_utc),utc(r.target_btc_close_time_utc)
        obs=day(r.observation_date)
        if target!=expected_close: raise IntegrityError('Wrong origin target close')
        if not t<=capture<target or capture>now: raise IntegrityError('Late/backdated/future capture')
        if obs>capture.normalize(): raise IntegrityError('Future observation date')
        url=f'https://fred.stlouisfed.org/series/{r.series_id}'
        if r.source_url!=url: raise IntegrityError('Wrong official series URL')
        if r.source_sha256!=observation_hash(r.series_id,r.observation_date,r.value,url): raise IntegrityError('Observation hash mismatch')
        values[series[r.series_id]]=float(decimal_text(r.value))
    return values

def check_frozen_files(root:Path,pins:dict):
    for name,expected in pins.items():
        p=root/name
        if not p.is_file() or digest(p.read_bytes())!=expected: raise IntegrityError(f'Frozen content changed: {name}')
    baseline=json.loads((root/'BASELINE_FREEZE_v2.json').read_text())
    canonical=json.dumps(baseline['manifest'],sort_keys=True,separators=(',',':')).encode()
    if digest(canonical)!=baseline['sha256']: raise IntegrityError('Baseline manifest canonical hash mismatch')

def validate_daily(frame,*,require_contiguous=True):
    if not {'time','close'}.issubset(frame.columns) or frame.empty: raise IntegrityError('Empty/missing daily time/close')
    d=frame.copy();d['time']=[utc(t) for t in d.time]
    if d.time.duplicated().any(): raise IntegrityError('Duplicate daily date')
    if not (d.time==d.time.dt.normalize()).all(): raise IntegrityError('Daily candle date must be UTC midnight')
    d=d.sort_values('time').reset_index(drop=True);close=pd.to_numeric(d.close,errors='raise')
    if not (np.isfinite(close)&(close>0)).all(): raise IntegrityError('Invalid daily price')
    if require_contiguous and not (d.time.diff().dropna()==pd.Timedelta(days=1)).all(): raise IntegrityError('Calendar gap: row offsets are not calendar horizons')
    return d

def calendar_targets(frame,h):
    if not isinstance(h,int) or h<=0: raise IntegrityError('Positive integer horizon required')
    d=validate_daily(frame);p=d.set_index('time').close.astype(float)
    return np.log(p.shift(-h)/p)

def eligible_training_mask(origins,label_end,available_at,forecast_time):
    t=utc(forecast_time)
    o,e,a=map(lambda xs:pd.DatetimeIndex([utc(x) for x in xs]),(origins,label_end,available_at))
    if len(o)!=len(e) or len(o)!=len(a) or not (o<=e).all(): raise IntegrityError('Invalid label timing arrays')
    return np.asarray((o<t)&(e<=t)&(a<=t))

def validation_labels_mask(origins,h,validation_end):
    end=utc(validation_end)
    return np.array([utc(o)+pd.Timedelta(days=h)<=end for o in origins])

def origin_hash(origins:Iterable): return digest('\n'.join(utc(t).isoformat() for t in origins).encode())

def pair_predictions(left,right,*,strict=False):
    def prep(d):
        if not {'time','prediction','actual'}.issubset(d.columns): raise IntegrityError('Missing prediction fields')
        d=d[['time','prediction','actual']].copy();d['time']=[utc(t) for t in d.time]
        if d.time.duplicated().any(): raise IntegrityError('Duplicate prediction origin')
        if not np.isfinite(d[['prediction','actual']].to_numpy(float)).all(): raise IntegrityError('Nonfinite prediction/outcome')
        return d.sort_values('time')
    a,b=prep(left),prep(right)
    c=a.merge(b,on='time',how='inner',validate='one_to_one',suffixes=('_base','_candidate'))
    if strict and (len(c)!=len(a) or len(c)!=len(b)): raise IntegrityError('Different forecast-origin sets')
    if not np.allclose(c.actual_base,c.actual_candidate,rtol=0,atol=1e-12): raise IntegrityError('Different outcomes at same origin')
    coverage={'baseline_n':len(a),'candidate_n':len(b),'common_n':len(c),'baseline_excluded':len(a)-len(c),'candidate_excluded':len(b)-len(c),'origin_set_sha256':origin_hash(c.time)}
    return c,coverage

def metrics(prediction,actual,*,origin_vol=None):
    p,a=np.asarray(prediction,float),np.asarray(actual,float)
    if len(p)==0 or len(p)!=len(a) or not np.isfinite(np.c_[p,a]).all(): raise IntegrityError('Invalid metric inputs')
    e=p-a;actual_up,predicted_up=a>0,p>0
    recalls=[float((predicted_up[actual_up==label]==label).mean()) for label in [False,True] if np.any(actual_up==label)]
    return {'n':len(a),'mae':float(abs(e).mean()),'rmse':float(np.sqrt((e*e).mean())),'median_absolute_error':float(np.median(abs(e))),'signed_bias':float(e.mean()),'directional_accuracy':float((predicted_up==actual_up).mean()),'balanced_accuracy':float(np.mean(recalls)) if len(recalls)==2 else None,'ic':float(np.corrcoef(p,a)[0,1]) if np.std(p)>1e-12 and np.std(a)>1e-12 else None,'vol_normalized_mae':float(np.mean(abs(e)/np.asarray(origin_vol))) if origin_vol is not None and np.all(np.asarray(origin_vol)>0) else None}

def nonoverlap_indices(times,h):
    ts=[utc(t) for t in times]
    if ts!=sorted(set(ts)): raise IntegrityError('Nonoverlap requires unique sorted dates')
    chosen=[];last=None
    for i,t in enumerate(ts):
        if last is None or t>=last+pd.Timedelta(days=h):chosen.append(i);last=t
    return chosen

def paired_block_interval(pair,h,*,draws=2000,seed=20260904):
    n,length=len(pair),max(1,math.ceil(h/7))
    result={'block_length_origins':length,'replicates':draws,'interval_95':None,'interpretation':'DIAGNOSTIC_ONLY_NOT_MULTIPLE_TEST_ADJUSTED'}
    if n<8*length:return result|{'reason':'TOO_FEW_BLOCKS'}
    times=pd.DatetimeIndex(pair.time)
    if not (times[1:]-times[:-1]==pd.Timedelta(days=7)).all():return result|{'reason':'IRREGULAR_ORIGIN_GRID'}
    delta=abs(pair.prediction_candidate-pair.actual_candidate).to_numpy()-abs(pair.prediction_base-pair.actual_base).to_numpy()
    rng=np.random.default_rng(seed);starts=rng.integers(0,n-length+1,size=(draws,math.ceil(n/length)))
    samples=(starts[:,:,None]+np.arange(length)).reshape(draws,-1)[:,:n];means=delta[samples].mean(axis=1)
    return result|{'paired_mae_difference':float(delta.mean()),'interval_95':np.quantile(means,[.025,.975]).tolist(),'reason':None}

KLINE_COLUMNS=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','taker_buy_base','taker_buy_quote','ignore']
FUNDING_COLUMNS=['calc_time','funding_interval_hours','last_funding_rate']

def parse_archive_csv(raw,kind):
    if kind not in ('klines','fundingRate'):raise IntegrityError('Unregistered archive schema')
    names=KLINE_COLUMNS if kind=='klines' else FUNDING_COLUMNS
    d=pd.read_csv(io.BytesIO(raw),header=None,dtype=str,keep_default_na=False)
    if d.empty or d.shape[1]!=len(names):raise IntegrityError('Empty/wrong-width archive')
    if str(d.iat[0,0]).strip()==names[0]:d=d.iloc[1:].reset_index(drop=True)
    d.columns=names
    for col in names:d[col]=pd.to_numeric(d[col],errors='raise')
    if d.empty:raise IntegrityError('Archive contains no data')
    ts=d[names[0]]
    if not np.isfinite(ts).all() or (ts<=0).any():raise IntegrityError('Invalid archive timestamp')
    d['time']=ts.map(lambda x:pd.to_datetime(int(x),unit='us' if x>10**14 else 'ms',utc=True))
    if d.time.duplicated().any():raise IntegrityError('Duplicate archive timestamp')
    return d
