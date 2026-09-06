#!/usr/bin/env python3
"""Research-only BTC calendar DCA robustness backtest.

Isolated from the frozen forecasting/promotion stack: no forecast model, feature,
split, threshold or promotion state is changed.

Tests one fixed-size BTC purchase per month for every combination of ordinal
week-of-month 1..4, weekday, and current Merida clock hour. Source is official
Binance Vision BTCUSDT spot 1h klines. Execution proxy is hourly OPEN. Historical
candles are mapped to fixed UTC-06:00 (Merida's current year-round clock), not
Mexico's former DST clock. If Binance has no candle at a scheduled hour because
of an exchange/data gap, execution moves to the first available hourly open
within 48 hours; the fallback count is reported.
"""
from __future__ import annotations
import calendar, csv, io, json, statistics, time, urllib.request, zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone

SYMBOL='BTCUSDT'; INTERVAL='1h'; TZ=timezone(timedelta(hours=-6))
START_YM=(2018,1); END_YM=(2026,8); BUY_USD=100.0
BASE='https://data.binance.vision/data/spot'
PERIODS=('2018-2021','2022-2023','2024-2026-08')
WEEKDAYS=['Mon','Tue','Wed','Thu','Fri','Sat','Sun']


def month_iter(start,end):
    y,m=start
    while (y,m)<=end:
        yield y,m
        y,m=(y+1,1) if m==12 else (y,m+1)

def next_month(y,m): return (y+1,1) if m==12 else (y,m+1)

def fetch_bytes(url,retries=4):
    req=urllib.request.Request(url,headers={'User-Agent':'btc-calendar-dca-research/1.3'})
    last=None
    for i in range(retries):
        try:
            with urllib.request.urlopen(req,timeout=45) as r: return r.read()
        except Exception as e:
            last=e; time.sleep(1.5*(i+1))
    raise RuntimeError(f'download failed: {url}: {last}')

def parse_zip(blob):
    out=[]
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names=[n for n in z.namelist() if n.endswith('.csv')]
        if len(names)!=1: raise RuntimeError(f'unexpected zip members: {z.namelist()}')
        text=io.TextIOWrapper(z.open(names[0]),encoding='utf-8')
        for row in csv.reader(text):
            if not row or not row[0].lstrip('-').isdigit(): continue
            ts=int(row[0]); sec=ts/(1_000_000 if ts>=100_000_000_000_000 else 1_000)
            out.append((datetime.fromtimestamp(sec,tz=timezone.utc),float(row[1])))
    return out

def load_daily(y,m,d):
    name=f'{SYMBOL}-{INTERVAL}-{y:04d}-{m:02d}-{d:02d}.zip'
    return parse_zip(fetch_bytes(f'{BASE}/daily/klines/{SYMBOL}/{INTERVAL}/{name}'))

def load_utc_month(y,m):
    name=f'{SYMBOL}-{INTERVAL}-{y:04d}-{m:02d}.zip'
    try: return parse_zip(fetch_bytes(f'{BASE}/monthly/klines/{SYMBOL}/{INTERVAL}/{name}'))
    except Exception:
        rows=[]
        for d in range(1,calendar.monthrange(y,m)[1]+1): rows.extend(load_daily(y,m,d))
        return rows

def load_local_month(y,m):
    rows=load_utc_month(y,m); ny,nm=next_month(y,m); rows.extend(load_daily(ny,nm,1))
    mp={}
    for dt_utc,price in rows:
        local=dt_utc.astimezone(TZ).replace(minute=0,second=0,microsecond=0)
        if (local.year,local.month)==(y,m): mp[local]=price
    return mp

def period_label(dt):
    ym=(dt.year,dt.month)
    if ym<=(2021,12): return '2018-2021'
    if ym<=(2023,12): return '2022-2023'
    return '2024-2026-08'

def occurrence_day(y,m,ordinal,weekday):
    first_wd=datetime(y,m,1).weekday()
    return 1+((weekday-first_wd)%7)+7*(ordinal-1)

def rank_rows(rows):
    rows=sorted(rows,key=lambda x:x['btc'],reverse=True); n=len(rows)
    for i,r in enumerate(rows,1): r['rank']=i; r['pct_rank']=i/n
    return rows

def main():
    month_maps={}; candles_loaded=0
    months=list(month_iter(START_YM,END_YM))
    for y,m in months:
        mp=load_local_month(y,m); month_maps[(y,m)]=mp; candles_loaded+=len(mp)

    combos=[]; fallback_total=0; max_delay=0
    for w in range(1,5):
      for wd in range(7):
       for h in range(24):
        per=defaultdict(float); counts=defaultdict(int); total=0.0; fallbacks=0
        for y,m in months:
            day=occurrence_day(y,m,w,wd)
            target=datetime(y,m,day,h,tzinfo=TZ)
            mp=month_maps[(y,m)]; actual=target; price=mp.get(actual); delay=0
            while price is None and delay<48:
                delay+=1; actual=target+timedelta(hours=delay); price=mp.get(actual)
            if price is None: raise RuntimeError(f'no execution within 48h: {target.isoformat()}')
            if delay:
                fallbacks+=1; fallback_total+=1; max_delay=max(max_delay,delay)
            b=BUY_USD/price; total+=b; p=period_label(target); per[p]+=b; counts[p]+=1
        combos.append({'week':w,'weekday':WEEKDAYS[wd],'weekday_num':wd,'hour_local':h,
                       'btc':total,'n_months':len(months),'fallbacks':fallbacks,
                       'period_btc':dict(per),'period_n':dict(counts)})

    ranked=rank_rows([dict(x) for x in combos])
    allrank={(r['week'],r['weekday_num'],r['hour_local']):r for r in ranked}
    period_ranks={}
    for p in PERIODS:
        rr=rank_rows([{'week':x['week'],'weekday':x['weekday'],'weekday_num':x['weekday_num'],
                       'hour_local':x['hour_local'],'btc':x['period_btc'][p],
                       'n_months':x['period_n'][p]} for x in combos])
        period_ranks[p]={(r['week'],r['weekday_num'],r['hour_local']):r for r in rr}

    robust=[]
    for x in combos:
        k=(x['week'],x['weekday_num'],x['hour_local'])
        prs=[period_ranks[p][k]['pct_rank'] for p in PERIODS]
        robust.append({'week':x['week'],'weekday':x['weekday'],'weekday_num':x['weekday_num'],
                       'hour_local':x['hour_local'],'btc':x['btc'],'full_rank':allrank[k]['rank'],
                       'era_pct_ranks':{p:period_ranks[p][k]['pct_rank'] for p in PERIODS},
                       'robust_score':sum(prs)/3,'worst_era_pct_rank':max(prs)})
    robust.sort(key=lambda r:(r['robust_score'],r['worst_era_pct_rank'],-r['btc']))

    proposed=[]
    for h in (13,14,15):
        k=(1,0,h); r=allrank[k]
        proposed.append({'week':1,'weekday':'Mon','hour_local':h,'full_rank':r['rank'],
                         'full_pct_rank':r['pct_rank'],'btc':r['btc'],
                         'era_pct_ranks':{p:period_ranks[p][k]['pct_rank'] for p in PERIODS}})
    monday=sorted((r for r in ranked if r['weekday_num']==0),key=lambda r:r['btc'],reverse=True)
    firstweek=sorted((r for r in ranked if r['week']==1),key=lambda r:r['btc'],reverse=True)
    median=statistics.median(r['btc'] for r in ranked); best=ranked[0]; worst=ranked[-1]
    def compact(r): return {k:r[k] for k in ('week','weekday','hour_local','btc','rank','pct_rank','n_months','fallbacks') if k in r}
    result={'status':'RESEARCH_ONLY_NOT_FORECAST_SIGNAL','source':'official Binance Vision spot BTCUSDT 1h klines',
            'timezone':'fixed UTC-06:00 (current Merida clock)','period':'2018-01-01 through 2026-08-31',
            'months':len(months),'candles_loaded':candles_loaded,'candidates':len(ranked),
            'purchase_rule':'$100 once/month at scheduled hourly OPEN; if exchange/data gap, first available OPEN <=48h; fees/slippage excluded',
            'fallback_executions_across_all_candidates':fallback_total,'max_fallback_delay_hours':max_delay,
            'best_full_sample':compact(best),'worst_full_sample':compact(worst),'median_btc':median,
            'best_vs_median_pct':(best['btc']/median-1)*100,'best_vs_worst_pct':(best['btc']/worst['btc']-1)*100,
            'robust_top10':robust[:10],'best_monday':compact(monday[0]),'best_first_week':compact(firstweek[0]),
            'previous_proposal_first_monday_13_15':proposed,'era_winners':{}}
    for p in PERIODS:
        winner=min(period_ranks[p].values(),key=lambda r:r['rank'])
        result['era_winners'][p]={k:winner[k] for k in ('week','weekday','hour_local','btc','rank','pct_rank','n_months')}
    print('CALENDAR_DCA_RESULT='+json.dumps(result,sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
