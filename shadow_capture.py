from __future__ import annotations
import hashlib, io, json, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd
import requests

ROOT=Path('shadow')
OUT=ROOT/'preclose_macro_snapshots.csv'
PROBE=ROOT/'source_probe.json'
SERIES=['M2SL','WALCL','WTREGEN','RRPONTSYD','DFF','DGS2','DGS10','DFII10','DTWEXBGS','VIXCLS','NASDAQCOM','CPIAUCSL','UNRATE','PAYEMS']

def sha(b:bytes)->str: return hashlib.sha256(b).hexdigest()

def fetch_one(sid:str,asof:datetime,s:requests.Session)->dict:
    end=asof.date(); url=f'https://fred.stlouisfed.org/series/{sid}/downloaddata/{sid}.csv'
    raw=None; last=None
    for attempt in range(1,5):
        try:
            print(f'FRED static {sid} attempt={attempt}',flush=True)
            r=s.get(url,timeout=(15,30))
            r.raise_for_status(); raw=r.content; break
        except requests.RequestException as e:
            last=f'{type(e).__name__}: {e}'
            if attempt<4: time.sleep(2**attempt)
    if raw is None: raise RuntimeError(f'FRED static snapshot failed for {sid} after 4 attempts; last={last}')
    d=pd.read_csv(io.BytesIO(raw))
    if d.shape[1]<2: raise RuntimeError(f'FRED schema failure for {sid}')
    dates=pd.to_datetime(d.iloc[:,0],utc=True,errors='coerce')
    vals=pd.to_numeric(d.iloc[:,1].replace('.',pd.NA),errors='coerce')
    ok=dates.notna() & vals.notna() & (dates.dt.date<=end)
    if not ok.any(): raise RuntimeError(f'No current FRED value for {sid} as of {end}')
    j=dates[ok].idxmax()
    return {'series_id':sid,'value':float(vals.loc[j]),'observation_date':dates.loc[j].strftime('%Y-%m-%d'),'source_sha256':sha(raw),'source_url':url}

def fetch_all(now:datetime)->list[dict]:
    s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0 btc-shadow-preclose/1.1','Accept':'text/csv,*/*;q=0.8','Connection':'close'})
    return [fetch_one(sid,now,s) for sid in SERIES]

def main():
    mode='probe' if '--probe' in sys.argv else 'capture'
    now=datetime.now(timezone.utc)
    rows=fetch_all(now)
    if len(rows)!=len(SERIES): raise RuntimeError('Incomplete FRED source packet')
    if mode=='probe':
        payload={'status':'PASS','capture_time_utc':now.isoformat(),'series_count':len(rows),'series':[{'series_id':r['series_id'],'observation_date':r['observation_date'],'value':r['value'],'source_sha256':r['source_sha256']} for r in rows]}
        PROBE.write_text(json.dumps(payload,indent=2,sort_keys=True)); print(json.dumps(payload,indent=2,sort_keys=True)); return
    if now.weekday()!=0: raise RuntimeError(f'Capture mode must run Monday UTC; got {now.isoformat()}')
    origin=now.date(); target_close=datetime.combine(origin+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc)
    if not now<target_close: raise RuntimeError('Macro capture missed pre-close timing invariant')
    out=[]
    for r in rows:
        out.append({'origin_date':origin.isoformat(),'capture_time_utc':now.isoformat(),'target_btc_close_time_utc':target_close.isoformat(),'series_id':r['series_id'],'value':r['value'],'observation_date':r['observation_date'],'source_sha256':r['source_sha256'],'source_url':r['source_url']})
    old=pd.read_csv(OUT) if OUT.exists() and OUT.stat().st_size else pd.DataFrame()
    if not old.empty and (old.origin_date.astype(str)==origin.isoformat()).any():
        existing=old[old.origin_date.astype(str)==origin.isoformat()]
        if set(existing.series_id)==set(SERIES) and len(existing)==len(SERIES):
            print(f'Pre-close packet already captured for {origin}; no-op'); return
        raise RuntimeError(f'Partial pre-close packet already exists for {origin}')
    merged=pd.concat([old,pd.DataFrame(out)],ignore_index=True)
    merged.to_csv(OUT,index=False)
    print(json.dumps({'status':'PASS','origin_date':origin.isoformat(),'capture_time_utc':now.isoformat(),'target_btc_close_time_utc':target_close.isoformat(),'series_count':len(out)},indent=2))
if __name__=='__main__': main()
