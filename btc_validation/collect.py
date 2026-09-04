"""Corrected official Binance ingestion. Retrieved archives are NOT original PIT proof.
Source absence, schema failure and transport failure remain distinct; no paid sources.
"""
from __future__ import annotations
import argparse,io,json,time,zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import numpy as np
import pandas as pd
import requests
from .core import IntegrityError,parse_archive_csv,digest,validate_daily
BASE='https://data.binance.vision/data/futures/um';SYMBOL='BTCUSDT'

def fetch_zip(url):
    row={'url':url,'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
    for attempt in range(3):
        try:
            response=requests.get(url,timeout=30,headers={'User-Agent':'btc-integrity-research/1.0'})
            if response.status_code==404:return None,row|{'status':'ARCHIVE_NOT_AVAILABLE'}
            response.raise_for_status();raw=response.content
            checksum=requests.get(url+'.CHECKSUM',timeout=20);checksum.raise_for_status()
            expected=checksum.text.strip().split()[0].lower()
            if expected!=digest(raw):raise IntegrityError('Archive checksum mismatch')
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                names=[x for x in z.namelist() if x.endswith('.csv')]
                if len(names)!=1:raise IntegrityError('Unexpected archive member count')
                payload=z.read(names[0])
            return payload,row|{'status':'CHECKSUM_VERIFIED','sha256':digest(raw),'csv_sha256':digest(payload),'bytes':len(raw)}
        except (requests.RequestException,zipfile.BadZipFile,IntegrityError) as exc:
            if attempt==2:return None,row|{'status':'SOURCE_FAILURE','error':f'{type(exc).__name__}: {exc}'}
            time.sleep(.5*(2**attempt))
    raise AssertionError('unreachable')

def metrics_day(raw,date):
    m=pd.read_csv(io.BytesIO(raw));required={'create_time','symbol','sum_open_interest'}
    if not required.issubset(m.columns):raise IntegrityError('Unknown metrics schema')
    if not (m.symbol==SYMBOL).all():raise IntegrityError('Wrong derivatives symbol')
    m['time']=pd.to_datetime(m.create_time,utc=True,errors='raise')
    if m.time.duplicated().any() or not (m.time.dt.normalize()==date).all():raise IntegrityError('Duplicate/wrong-date metrics timestamps')
    if m.empty:raise IntegrityError('Empty metrics archive')
    r=m.sort_values('time').iloc[-1]
    return {'time':date,'metrics_observed_at':r.time,'oi_btc':pd.to_numeric(r['sum_open_interest'],errors='raise'),'global_accounts_ls':pd.to_numeric(r.get('count_long_short_ratio'),errors='coerce'),'top_positions_ls':pd.to_numeric(r.get('sum_toptrader_long_short_ratio'),errors='coerce')}

def assemble(prices,funding,metric_rows,start,end):
    if not prices:raise IntegrityError('No verified futures prices')
    p=pd.concat(prices,ignore_index=True)
    if p.time.duplicated().any():raise IntegrityError('Duplicate monthly price boundary')
    p=validate_daily(p,require_contiguous=False);p=p.set_index('time').reindex(pd.date_range(start,end,freq='D',tz='UTC'));p.index.name='time'
    if funding:
        f=pd.concat(funding,ignore_index=True)
        if f.time.duplicated().any():raise IntegrityError('Duplicate funding timestamp')
        f['date']=f.time.dt.normalize();valid=f.last_funding_rate.notna();sums=f.loc[valid].groupby('date').funding_interval_hours.sum();observed=f.groupby('date').last_funding_rate.mean();observed=observed.where(sums==24);p['funding_daily']=observed.reindex(p.index)
    else:p['funding_daily']=np.nan
    m=pd.DataFrame(metric_rows)
    if not m.empty:
        if m.time.duplicated().any():raise IntegrityError('Duplicate metrics date')
        p=p.join(m.set_index('time'),how='left')
    else:
        for col in ['oi_btc','global_accounts_ls','top_positions_ls']:p[col]=np.nan
    oi=pd.to_numeric(p.oi_btc,errors='raise').where(p.oi_btc>0)
    p['oi_btc_chg_1d']=np.log(oi).diff(1);p['oi_btc_chg_7d']=np.log(oi).diff(7);p['funding_mean_7d']=p.funding_daily.rolling(7,min_periods=7).mean()
    total=pd.to_numeric(p.quote_volume,errors='raise');buy=pd.to_numeric(p.taker_buy_quote,errors='raise')
    if ((buy<0)|(buy>total)|(total<0)).any():raise IntegrityError('Impossible taker volumes')
    p['taker_imbalance_1d']=(2*buy-total)/total.where(total>0)
    p['taker_imbalance_7d']=(2*buy.rolling(7).sum()-total.rolling(7).sum())/total.rolling(7).sum().where(lambda x:x>0)
    return p.reset_index()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',default='validation_inputs/corrected');args=ap.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    cfg=json.loads(Path('btc_validation/RESEARCH_FREEZE_v1.json').read_text());start,end=pd.Timestamp('2020-09-01',tz='UTC'),pd.Timestamp(cfg['history_last_date'],tz='UTC');jobs=[]
    for month in pd.date_range(start,end,freq='MS'):
        tag=month.strftime('%Y-%m');jobs += [('klines',month,f'{BASE}/monthly/klines/{SYMBOL}/1d/{SYMBOL}-1d-{tag}.zip'),('fundingRate',month,f'{BASE}/monthly/fundingRate/{SYMBOL}/{SYMBOL}-fundingRate-{tag}.zip')]
    for d in pd.date_range('2020-09-10',end,freq='D',tz='UTC'):jobs.append(('metrics',d,f'{BASE}/daily/metrics/{SYMBOL}/{SYMBOL}-metrics-{d.date()}.zip'))
    def one(job):
        kind,d,url=job;payload,manifest=fetch_zip(url)
        if payload is None:return kind,None,manifest
        try:return kind,(metrics_day(payload,d) if kind=='metrics' else parse_archive_csv(payload,kind)),manifest
        except Exception as exc:return kind,None,manifest|{'status':'SCHEMA_FAILURE','error':f'{type(exc).__name__}: {exc}'}
    prices,funding,ms,log=[],[],[],[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for kind,data,item in pool.map(one,jobs):
            log.append(item)
            if data is not None:{'klines':prices,'fundingRate':funding,'metrics':ms}[kind].append(data)
    (out/'source_manifest.json').write_text(json.dumps(log,indent=2));failed=[x for x in log if x['status'] in ['SOURCE_FAILURE','SCHEMA_FAILURE']]
    d=assemble(prices,funding,ms,str(start.date()),str(end.date()));d.to_csv(out/'daily.csv',index=False);coverage=[]
    for family,cols in cfg['derivative_families'].items():
        for year,g in d.groupby(d.time.dt.year):
            valid=g[cols].notna().all(axis=1);coverage.append({'family':family,'year':int(year),'calendar_days':len(g),'complete_days':int(valid.sum()),'first_complete':str(g.loc[valid,'time'].min().date()) if valid.any() else None})
    status={'status':'SOURCE_FAILURE' if failed else 'RETRIEVAL_COMPLETE_DIAGNOSTIC_ONLY','pit_status':'OFFICIAL_ARCHIVE_AS_RETRIEVED_NOT_ORIGINAL_VINTAGE_PROOF','source_failures':len(failed),'archive_absences':sum(x['status']=='ARCHIVE_NOT_AVAILABLE' for x in log),'daily_sha256':digest((out/'daily.csv').read_bytes()),'coverage':coverage,'promotion_allowed':False}
    (out/'coverage.json').write_text(json.dumps(status,indent=2));print(json.dumps(status,indent=2))
    if failed:raise IntegrityError(f'{len(failed)} source/schema failures; do not fit this data')

if __name__=='__main__':main()
