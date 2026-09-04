"""Separate post-publication shadow evidence. No tuning, probabilities or auto-promotion."""
from __future__ import annotations
import json,math,subprocess
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
import requests
from .core import IntegrityError,utc,day,digest,metrics,pair_predictions,nonoverlap_indices
from .runtime import MODELS,HORIZONS
PATH=Path('shadow/issued_forecasts.jsonl');EXPERIMENT='btc-issued-anchor-v1-20260904'

def canonical(record):return json.dumps({k:v for k,v in record.items() if k!='record_sha256'},sort_keys=True,separators=(',',':'),allow_nan=False)

def load_records(path=PATH):
    records=[json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    ids=[x['forecast_id'] for x in records]
    if len(ids)!=len(set(ids)):raise IntegrityError('Duplicate issued forecast')
    for x in records:validate_record(x)
    keys=[(x['feature_origin_date'],x['horizon_days'],x['model']) for x in records]
    if len(keys)!=len(set(keys)):raise IntegrityError('Duplicate semantic issued origin')
    for origin in set(x['feature_origin_date'] for x in records):
        group=[x for x in records if x['feature_origin_date']==origin]
        if {(x['horizon_days'],x['model']) for x in group}!={(h,m) for h in HORIZONS for m in MODELS}:raise IntegrityError('Partial committed issued origin')
        if len(set(x['period_start_utc'] for x in group))!=1:raise IntegrityError('Models have different future anchors')
    return records

def anchor_after(issued):return (utc(issued)+pd.Timedelta(minutes=15)).ceil('h')

def validate_record(x):
    if x['experiment_id']!=EXPERIMENT or x['model'] not in MODELS or x['horizon_days'] not in HORIZONS:raise IntegrityError('Unregistered issued experiment/model/horizon')
    origin=day(x['feature_origin_date'])
    if x['forecast_id']!=f"issued-v1::{x['feature_origin_date']}::{x['horizon_days']}::{x['model']}" or x['decision_weight']!=0:raise IntegrityError('Issued identity/decision-weight mismatch')
    if origin.weekday()!=0 or utc(x['data_as_of_utc'])!=origin+pd.Timedelta(days=1):raise IntegrityError('Wrong feature origin/as-of')
    issue,start,end=utc(x['issued_at_utc']),utc(x['period_start_utc']),utc(x['period_end_utc'])
    if not utc(x['data_as_of_utc'])<=issue or start!=anchor_after(issue) or end!=start+pd.Timedelta(days=x['horizon_days']):raise IntegrityError('Issued clock/horizon mismatch')
    if x['record_sha256']!=digest(canonical(x).encode()):raise IntegrityError('Issued record hash mismatch')
    if not np.isfinite(float(x['predicted_log_return'])):raise IntegrityError('Nonfinite issued prediction')

def append_issued(existing,legacy,origin,issued=None):
    issued=utc(issued) if issued is not None else pd.Timestamp.now(tz='UTC');os=str(utc(origin).date())
    old=[x for x in existing if x['feature_origin_date']==os]
    if old:
        if {(x['horizon_days'],x['model']) for x in old}!={(h,m) for h in HORIZONS for m in MODELS}:raise IntegrityError('Partial issued-origin set')
        return existing
    start=anchor_after(issued);new=[];g=legacy[legacy.origin_date.astype(str)==os]
    if len(g)!=len(HORIZONS)*len(MODELS):raise IntegrityError('Missing frozen predictions for issued shadow')
    for row in g.itertuples(index=False):
        x={'experiment_id':EXPERIMENT,'forecast_id':f'issued-v1::{os}::{int(row.horizon_days)}::{row.model}','feature_origin_date':os,'issued_at_utc':issued.isoformat(),'data_as_of_utc':(utc(origin)+pd.Timedelta(days=1)).isoformat(),'period_start_utc':start.isoformat(),'period_end_utc':(start+pd.Timedelta(days=int(row.horizon_days))).isoformat(),'model':row.model,'horizon_days':int(row.horizon_days),'predicted_log_return':float(row.predicted_log_return),'decision_weight':0}
        x['record_sha256']=digest(canonical(x).encode());validate_record(x);new.append(x)
    return existing+new

def publication_proof(record,path=PATH):
    result=subprocess.run(['git','log','--reverse','--format=%H','-S',record['forecast_id'],'--',str(path)],capture_output=True,text=True,check=True)
    commits=result.stdout.splitlines()
    if not commits:return None
    sha=commits[0];text=subprocess.check_output(['git','show',f'{sha}:{path}'],text=True)
    matches=[json.loads(line) for line in text.splitlines() if line.strip() and json.loads(line).get('forecast_id')==record['forecast_id']]
    if len(matches)!=1 or matches[0]!=record:raise IntegrityError('Issued record differs from first publication')
    seconds=int(subprocess.check_output(['git','show','-s','--format=%ct',sha],text=True).strip());published=pd.to_datetime(seconds,unit='s',utc=True)
    if published>=utc(record['period_start_utc']):raise IntegrityError('Forecast committed after target started')
    return {'commit_sha':sha,'published_at_utc':published.isoformat()}

def price_at(timestamp,*,now=None):
    t=utc(timestamp);n=utc(now) if now is not None else pd.Timestamp.now(tz='UTC')
    if n<t+pd.Timedelta(minutes=1):return None
    url='https://data-api.binance.vision/api/v3/klines';params={'symbol':'BTCUSDT','interval':'1m','startTime':int(t.timestamp()*1000),'endTime':int(t.timestamp()*1000)+59999,'limit':1}
    response=requests.get(url,params=params,timeout=20);response.raise_for_status();rows=response.json()
    if not isinstance(rows,list) or len(rows)!=1 or len(rows[0])<7 or int(rows[0][0])!=params['startTime']:raise IntegrityError('Missing exact issued-anchor bar')
    if int(rows[0][6])>int(n.timestamp()*1000):raise IntegrityError('Unclosed anchor bar')
    value=float(rows[0][1])
    if not np.isfinite(value) or value<=0:raise IntegrityError('Invalid issued-anchor price')
    return value,{'url':url,'params':params,'source_sha256':digest(response.content),'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}

def evaluate(records,*,now=None,resolve=publication_proof,prices=price_at):
    n=utc(now) if now is not None else pd.Timestamp.now(tz='UTC');complete=[];health=[];cache={}
    for x in records:
        validate_record(x);end=utc(x['period_end_utc'])
        try:
            proof=resolve(x)
            if proof is None:health.append({'forecast_id':x['forecast_id'],'status':'AWAITING_PUBLICATION_PROOF'});continue
            if n<end+pd.Timedelta(minutes=1):health.append({'forecast_id':x['forecast_id'],'status':'PENDING_OUTCOME'});continue
            endpoints=[]
            for field in ['period_start_utc','period_end_utc']:
                t=x[field]
                if t not in cache:cache[t]=prices(t,now=n)
                if cache[t] is None:raise IntegrityError('Missing mature anchor')
                endpoints.append(cache[t])
            a,b=endpoints
            complete.append({'time':utc(x['period_start_utc']),'horizon':x['horizon_days'],'model':x['model'],'prediction':x['predicted_log_return'],'actual':math.log(b[0]/a[0]),'anchor_price':a[0],'target_price':b[0],'forecast_id':x['forecast_id'],'publication_commit':proof['commit_sha'],'anchor_source':json.dumps(a[1],sort_keys=True),'target_source':json.dumps(b[1],sort_keys=True)})
        except (IntegrityError,requests.RequestException,subprocess.CalledProcessError) as exc:health.append({'forecast_id':x['forecast_id'],'status':'EVIDENCE_FAILURE','error':str(exc)})
    return pd.DataFrame(complete),health

def save_state(records):
    frame,health=evaluate(records);rows=[]
    if not frame.empty:
        for h,g in frame.groupby('horizon'):
            a=g[g.model=='price_ridge'][['time','prediction','actual']];b=g[g.model=='price_macro_ridge'][['time','prediction','actual']]
            pair,cov=pair_predictions(a,b,strict=True)
            if pair.empty:continue
            for name in ['price_ridge','price_macro_ridge']:
                x=g[g.model==name].sort_values('time');rows.append({'horizon_days':h,'model':name,**metrics(x.prediction,x.actual),'nonoverlap_n':len(nonoverlap_indices(x.time,int(h))),'origin_set_sha256':cov['origin_set_sha256'],'evaluation_class':'PUBLISHED_BEFORE_FUTURE_ANCHOR'})
    Path('shadow/issued_outcomes.csv').write_text(frame.to_csv(index=False));Path('shadow/issued_scorecard.csv').write_text(pd.DataFrame(rows).to_csv(index=False))
    status={'experiment_id':EXPERIMENT,'issued_rows':len(records),'completed_rows':len(frame),'distinct_feature_origins':len(set(x['feature_origin_date'] for x in records)),'evidence_failures':sum(x['status']=='EVIDENCE_FAILURE' for x in health),'status':'EXPERIMENTAL_NO_AUTO_PROMOTION','decision_grade':False,'probabilities_calibrated':False,'row_status':health,'updated_at_utc':datetime.now(timezone.utc).isoformat()}
    Path('shadow/issued_status.json').write_text(json.dumps(status,indent=2));return status
