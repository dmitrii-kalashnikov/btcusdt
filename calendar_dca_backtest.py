#!/usr/bin/env python3
"""Research-only BTC calendar DCA backtest.

This script is deliberately isolated from the frozen forecasting/promotion stack.
It does not alter model features, splits, thresholds, forecasts, or promotion state.

Question: for one fixed-size BTC purchase per month, which combination of
ordinal week-of-month (1..4), weekday, and current Merida clock hour historically
bought most BTC?

Source: official Binance Vision spot BTCUSDT 1h klines.
Execution price proxy: hourly candle OPEN (appropriate for an automated order
scheduled at the start of the local hour; fees/slippage excluded).
Timezone: fixed UTC-06:00, matching Merida's current year-round clock. This is
intentional: the output is a schedule to use now, so historical candles are
mapped to today's Merida clock rather than Mexico's pre-2023 DST regime.
"""

from __future__ import annotations

import calendar
import csv
import io
import json
import statistics
import time
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone

SYMBOL = "BTCUSDT"
INTERVAL = "1h"
TZ = timezone(timedelta(hours=-6))
START_YM = (2018, 1)
END_YM = (2026, 8)
BUY_USD = 100.0
BASE = "https://data.binance.vision/data/spot"


def month_iter(start, end):
    y, m = start
    while (y, m) <= end:
        yield y, m
        m += 1
        if m == 13:
            y += 1
            m = 1


def next_month(y, m):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def fetch_bytes(url, retries=4):
    req = urllib.request.Request(url, headers={"User-Agent": "btc-calendar-dca-research/1.1"})
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"download failed: {url}: {last}")


def parse_zip(blob):
    out = []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.endswith('.csv')]
        if len(names) != 1:
            raise RuntimeError(f"unexpected zip members: {z.namelist()}")
        text = io.TextIOWrapper(z.open(names[0]), encoding='utf-8')
        for row in csv.reader(text):
            if not row or not row[0].lstrip('-').isdigit():
                continue
            raw_ts = int(row[0])
            # Binance spot archive switched to microseconds from 2025-01-01.
            sec = raw_ts / (1_000_000 if raw_ts >= 100_000_000_000_000 else 1_000)
            dt_utc = datetime.fromtimestamp(sec, tz=timezone.utc)
            op = float(row[1])
            out.append((dt_utc, op))
    return out


def load_daily(y, m, d):
    name = f"{SYMBOL}-{INTERVAL}-{y:04d}-{m:02d}-{d:02d}.zip"
    url = f"{BASE}/daily/klines/{SYMBOL}/{INTERVAL}/{name}"
    return parse_zip(fetch_bytes(url))


def load_utc_month(y, m):
    name = f"{SYMBOL}-{INTERVAL}-{y:04d}-{m:02d}.zip"
    monthly = f"{BASE}/monthly/klines/{SYMBOL}/{INTERVAL}/{name}"
    try:
        return parse_zip(fetch_bytes(monthly))
    except Exception:
        # Recent month may not yet have a monthly bundle. Fall back to daily files.
        rows = []
        for d in range(1, calendar.monthrange(y, m)[1] + 1):
            rows.extend(load_daily(y, m, d))
        return rows


def load_local_month(y, m):
    # A UTC-06 local month ends six hours into the next UTC month, so append
    # next month's UTC day 1 and filter after conversion.
    rows = load_utc_month(y, m)
    ny, nm = next_month(y, m)
    rows.extend(load_daily(ny, nm, 1))
    return rows


def period_label(dt):
    ym = (dt.year, dt.month)
    if (2018, 1) <= ym <= (2021, 12):
        return "2018-2021"
    if (2022, 1) <= ym <= (2023, 12):
        return "2022-2023"
    if (2024, 1) <= ym <= (2026, 8):
        return "2024-2026-08"
    raise ValueError(ym)


def rank_rows(rows):
    rows = sorted(rows, key=lambda x: x['btc'], reverse=True)
    n = len(rows)
    for i, r in enumerate(rows, 1):
        r['rank'] = i
        r['pct_rank'] = i / n
    return rows


def main():
    # key = (ordinal_week, weekday[Mon=0], current-Merida hour)
    buys = defaultdict(list)
    month_count = 0
    candle_count = 0

    for y, m in month_iter(START_YM, END_YM):
        rows = load_local_month(y, m)
        month_count += 1
        candle_count += len(rows)
        seen = set()
        for dt_utc, price in rows:
            local = dt_utc.astimezone(TZ)
            if (local.year, local.month) != (y, m):
                continue
            ordinal_week = (local.day - 1) // 7 + 1
            if ordinal_week > 4:
                continue  # 5th occurrence is not present every month; unfair spend count.
            key = (ordinal_week, local.weekday(), local.hour)
            id_key = (y, m, key)
            if id_key in seen:
                raise RuntimeError(f"duplicate local slot {id_key}")
            seen.add(id_key)
            buys[key].append((local, price))

    expected_months = month_count
    combos = []
    weekdays = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    for w in range(1, 5):
        for wd in range(7):
            for h in range(24):
                key = (w, wd, h)
                obs = buys.get(key, [])
                if len(obs) != expected_months:
                    raise RuntimeError(f"incomplete combo {key}: {len(obs)} != {expected_months}")
                per = defaultdict(float)
                counts = defaultdict(int)
                all_btc = 0.0
                for dt, price in obs:
                    b = BUY_USD / price
                    all_btc += b
                    p = period_label(dt)
                    per[p] += b
                    counts[p] += 1
                combos.append({
                    'week': w,
                    'weekday': weekdays[wd],
                    'weekday_num': wd,
                    'hour_local': h,
                    'btc': all_btc,
                    'n_months': len(obs),
                    'period_btc': dict(per),
                    'period_n': dict(counts),
                })

    ranked_all = rank_rows([dict(x) for x in combos])
    all_rank = {(r['week'],r['weekday_num'],r['hour_local']): r for r in ranked_all}

    period_ranks = {}
    for p in ['2018-2021','2022-2023','2024-2026-08']:
        rows = []
        for x in combos:
            rows.append({
                'week':x['week'],'weekday':x['weekday'],'weekday_num':x['weekday_num'],
                'hour_local':x['hour_local'],'btc':x['period_btc'][p],
                'n_months':x['period_n'][p]
            })
        rr = rank_rows(rows)
        period_ranks[p] = {(r['week'],r['weekday_num'],r['hour_local']): r for r in rr}

    # Robust score: average percentile rank across three non-overlapping eras.
    robust = []
    for x in combos:
        k=(x['week'],x['weekday_num'],x['hour_local'])
        prs=[period_ranks[p][k]['pct_rank'] for p in period_ranks]
        robust.append({
            'week':x['week'],'weekday':x['weekday'],'weekday_num':x['weekday_num'],
            'hour_local':x['hour_local'],'btc':x['btc'],
            'full_rank':all_rank[k]['rank'],
            'era_pct_ranks':{p:period_ranks[p][k]['pct_rank'] for p in period_ranks},
            'robust_score':sum(prs)/len(prs),
            'worst_era_pct_rank':max(prs),
        })
    robust.sort(key=lambda r:(r['robust_score'], r['worst_era_pct_rank'], -r['btc']))

    # Candidate previously proposed to user: first Monday around 14:00 current Merida time.
    proposed=[]
    for h in [13,14,15]:
        k=(1,0,h)
        proposed.append({
            'week':1,'weekday':'Mon','hour_local':h,
            'full_rank':all_rank[k]['rank'],
            'full_pct_rank':all_rank[k]['pct_rank'],
            'btc':all_rank[k]['btc'],
            'era_pct_ranks':{p:period_ranks[p][k]['pct_rank'] for p in period_ranks},
        })

    monday = [r for r in ranked_all if r['weekday_num']==0]
    monday.sort(key=lambda r:r['btc'], reverse=True)
    first_week = [r for r in ranked_all if r['week']==1]
    first_week.sort(key=lambda r:r['btc'], reverse=True)

    median_btc = statistics.median(r['btc'] for r in ranked_all)
    best = ranked_all[0]
    worst = ranked_all[-1]
    def compact(r):
        return {k:r[k] for k in ['week','weekday','hour_local','btc','rank','pct_rank','n_months'] if k in r}

    result = {
        'status':'RESEARCH_ONLY_NOT_FORECAST_SIGNAL',
        'source':'official Binance Vision spot BTCUSDT 1h klines',
        'timezone':'fixed UTC-06:00 (current Merida clock)',
        'period':'2018-01-01 through 2026-08-31',
        'months':month_count,
        'candles_loaded':candle_count,
        'candidates':len(ranked_all),
        'purchase_rule':'$100 once per month at hourly candle OPEN; week=ordinal 1..4; fees/slippage excluded',
        'best_full_sample':compact(best),
        'worst_full_sample':compact(worst),
        'median_btc':median_btc,
        'best_vs_median_pct':(best['btc']/median_btc-1)*100,
        'best_vs_worst_pct':(best['btc']/worst['btc']-1)*100,
        'robust_top10':robust[:10],
        'best_monday':compact(monday[0]),
        'best_first_week':compact(first_week[0]),
        'previous_proposal_first_monday_13_15':proposed,
        'era_winners':{},
    }
    for p in period_ranks:
        winner=min(period_ranks[p].values(), key=lambda r:r['rank'])
        result['era_winners'][p]={k:winner[k] for k in ['week','weekday','hour_local','btc','rank','pct_rank','n_months']}

    print('CALENDAR_DCA_RESULT=' + json.dumps(result, sort_keys=True, separators=(',',':')))


if __name__ == '__main__':
    main()
