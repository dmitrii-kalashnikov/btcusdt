"""Integrity overlay for the original frozen shadow; economic model unchanged."""
from __future__ import annotations
import json,math
from pathlib import Path
import numpy as np
import pandas as pd
from .core import IntegrityError,check_frozen_files,day,utc
MODELS=('price_ridge','price_macro_ridge','primary_equal_weight_ensemble')
HORIZONS=(7,30,90,180,365)

def check_runtime_contract(root=Path('.')):
    c=json.loads((root/'btc_validation/INTEGRITY_CONTRACT_v1.json').read_text())
    check_frozen_files(root,c['frozen_file_sha256']);return c

def validate_forecasts(f,*,complete_grid=True):
    if f.empty:return
    cols={'forecast_id','origin_date','capture_time_utc','spot_date','horizon_days','due_date','model','spot','predicted_log_return','forecast_price','p_up','status'}
    if f.columns.duplicated().any() or not cols.issubset(f.columns):raise IntegrityError('Forecast schema mismatch')
    if f.forecast_id.duplicated().any() or f.duplicated(['origin_date','horizon_days','model']).any():raise IntegrityError('Duplicate forecast is not additional evidence')
    for r in f.itertuples(index=False):
        t,due=day(r.origin_date),day(r.due_date);h=int(r.horizon_days)
        if float(r.horizon_days)!=h or h not in HORIZONS or r.model not in MODELS:raise IntegrityError('Unknown frozen model/horizon')
        if r.forecast_id!=f'{r.origin_date}::{h}::{r.model}':raise IntegrityError('Forecast identity mismatch')
        if r.spot_date!=r.origin_date or due!=t+pd.Timedelta(days=h):raise IntegrityError('Wrong forecast spot date/horizon')
        issued,data_asof=utc(r.capture_time_utc),t+pd.Timedelta(days=1)
        if not data_asof<=issued<due+pd.Timedelta(days=1):raise IntegrityError('Issued before inputs or after target maturity')
        vals=np.array([r.spot,r.predicted_log_return,r.forecast_price,r.p_up],dtype=float)
        if not np.isfinite(vals).all() or vals[0]<=0 or vals[2]<=0 or not 0<=vals[3]<=1:raise IntegrityError('Invalid numeric forecast')
        if not math.isclose(float(r.forecast_price),float(r.spot)*math.exp(float(r.predicted_log_return)),rel_tol=1e-8,abs_tol=1e-5):raise IntegrityError('Forecast price/return parity failed')
        if r.status not in ('PENDING','COMPLETE'):raise IntegrityError('Unknown forecast status')
        if r.status=='COMPLETE':
            for k in ('actual_price','actual_log_return','actual_up'):
                if not hasattr(r,k) or not np.isfinite(float(getattr(r,k))):raise IntegrityError('Complete forecast missing outcome')
            if float(r.actual_price)<=0:raise IntegrityError('Nonpositive actual price')
            expected=math.log(float(r.actual_price)/float(r.spot))
            if not math.isclose(float(r.actual_log_return),expected,rel_tol=1e-10,abs_tol=1e-10) or float(r.actual_up)!=float(expected>0):raise IntegrityError('Outcome/return/sign parity failed')
    if complete_grid:
        expected={(h,m) for h in HORIZONS for m in MODELS}
        for _,g in f.groupby('origin_date'):
            if set(zip(g.horizon_days.astype(int),g.model))!=expected:raise IntegrityError('Partial frozen origin cannot be idempotently complete')

def assert_forecasts_immutable(old,new):
    validate_forecasts(new)
    if old.empty:return
    stable=[c for c in old.columns if c not in ('status','actual_price','actual_log_return','actual_up')]
    a,b=old.set_index('forecast_id'),new.set_index('forecast_id')
    if not a.index.isin(b.index).all():raise IntegrityError('Historical forecast deleted')
    for key,r in a.iterrows():
        for col in stable:
            if col=='forecast_id':continue
            x,y=r[col],b.at[key,col]
            if pd.isna(x) and pd.isna(y):continue
            if x!=y:raise IntegrityError(f'Immutable forecast changed: {key}/{col}')
        if r.status=='COMPLETE' and any(r[c]!=b.at[key,c] for c in ('status','actual_price','actual_log_return','actual_up')):raise IntegrityError('Completed outcome rewritten')

def timing_audit(f):
    validate_forecasts(f)
    if f.empty:return {'delayed_origin_rows':0,'eligible_prospective_rows':0}
    late=sum(utc(r.capture_time_utc)>day(r.origin_date)+pd.Timedelta(days=1) for r in f.itertuples(index=False))
    return {'delayed_origin_rows':late,'eligible_prospective_rows':len(f)-late,'evaluation_class':'DELAYED_ORIGIN_DIAGNOSTIC' if late else 'ISSUED_BEFORE_TARGET_START','decision_grade':False,'probabilities_calibrated':False}

def expected_monday(now=None):
    n=utc(now) if now is not None else pd.Timestamp.now(tz='UTC')
    monday=n.normalize()-pd.Timedelta(days=n.weekday())
    if n<monday+pd.Timedelta(days=1):monday-=pd.Timedelta(days=7)
    return monday

def require_pair_proof(s):
    if s.empty:return
    required={'scope','horizon_days','model','n','origin_set_sha256','eligible_prospective_n'}
    if not required.issubset(s.columns):raise IntegrityError('Scorecard lacks paired-origin/issuance proof')
    if s.duplicated(['scope','horizon_days','model']).any():raise IntegrityError('Duplicate scorecard rows')
    for _,g in s.groupby(['scope','horizon_days']):
        if set(g.model)!={'price_ridge','price_macro_ridge'} or len(g)!=2:raise IntegrityError('Missing comparator row')
        if g.n.nunique()!=1 or g.origin_set_sha256.nunique()!=1 or g.eligible_prospective_n.nunique()!=1:raise IntegrityError('Unpaired review scorecard')
        n,e=pd.to_numeric(g.n),pd.to_numeric(g.eligible_prospective_n)
        if not ((n>0)&(n%1==0)&(e>=0)&(e%1==0)&(e<=n)).all():raise IntegrityError('Invalid sample size')
