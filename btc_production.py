"""Read-only market production report; no trading, model tuning or promotion.

One CSV feeds the existing Google Sheet. Source failures are explicit and never
filled with old numbers. Only successful complete Monday packets are appended.
"""
from __future__ import annotations
import argparse, csv, io, json, math, os, re, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import requests
from btc_validation.core import IntegrityError, digest, observation_hash, validate_packet
from btc_validation.runtime import check_runtime_contract, validate_forecasts
import shadow_sources as shadow

SPOT = 'https://data-api.binance.vision'
FUTURES = 'https://fapi.binance.com'
ETF = 'https://farside.co.uk/btc/'
REPO = 'https://github.com/dmitrii-kalashnikov/btcusdt'
OUT = Path('live')
AUDIT = Path('production_artifacts')
TTL_HOURS = 2


def utcnow():
    return pd.Timestamp.now(tz='UTC')


def number(value, *, positive=False):
    n = float(value)
    if not math.isfinite(n) or (positive and n <= 0):
        raise IntegrityError('Nonfinite or invalid positive measurement')
    return n


def timely(value, now, seconds):
    t = pd.to_datetime(int(value), unit='ms', utc=True)
    if not -60 <= (now-t).total_seconds() <= seconds:
        raise IntegrityError(f'Stale/future source timestamp: {t.isoformat()}')
    return t.isoformat()


def get(url, params=None):
    """Bounded GET-only transport. Do not retry access restrictions."""
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=(5, 18),
                             headers={'User-Agent': 'btc-readonly-production/1.0'})
            r.raise_for_status()
            if len(r.content) > 8_000_000:
                raise IntegrityError('Unexpectedly large source response')
            return r
        except requests.RequestException as exc:
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if attempt == 2 or (status is not None and status < 500 and status != 429):
                raise
            time.sleep(2 ** attempt)
    raise AssertionError('unreachable')


def evidence(r, observed=None):
    AUDIT.mkdir(parents=True,exist_ok=True)
    (AUDIT/(digest(r.content)+'.raw')).write_bytes(r.content)
    return {'url': r.url, 'retrieved_at_utc': utcnow().isoformat(),
            'observed_at_utc': observed, 'sha256': digest(r.content)}


def safe(name, fn):
    try:
        result = fn()
        return name, {'status': 'OK', **result}
    except Exception as exc:
        return name, {'status': 'UNAVAILABLE', 'error': f'{type(exc).__name__}: {exc}'[:600]}


def parse_klines(rows, interval, now):
    if not isinstance(rows, list) or not rows:
        raise IntegrityError('Empty kline response')
    values = []
    ms = int(pd.Timedelta(interval).total_seconds()*1000)
    for row in rows:
        if not isinstance(row, list) or len(row) != 12:
            raise IntegrityError('Unknown spot kline schema')
        start, end = int(row[0]), int(row[6])
        if start % ms or end != start + ms - 1:
            raise IntegrityError('Wrong kline interval boundary')
        if end >= int(now.timestamp()*1000):
            continue
        o,h,l,c = [number(row[i], positive=True) for i in (1,2,3,4)]
        volume,quote,buy = [number(row[i]) for i in (5,7,10)]
        if h < max(o,c) or l > min(o,c) or l > h or min(volume,quote,buy)<0 or buy>quote:
            raise IntegrityError('Impossible OHLC/volume')
        values.append({'time': pd.to_datetime(start,unit='ms',utc=True),
                       'close': c, 'high': h, 'low': l, 'quote': quote, 'buy': buy})
    d = pd.DataFrame(values)
    if d.empty or d.time.duplicated().any() or not d.time.is_monotonic_increasing:
        raise IntegrityError('Empty/duplicate/unordered closed candles')
    if not (d.time.diff().dropna()==pd.Timedelta(interval)).all():
        raise IntegrityError('Gap in candle calendar')
    expected = now.floor(interval)-pd.Timedelta(interval)
    if d.time.iloc[-1] != expected:
        raise IntegrityError('Missing latest fully closed candle')
    return d


def collect_spot():
    r=get(SPOT+'/api/v3/ticker/24hr', {'symbol':'BTCUSDT'}); q=r.json(); now=utcnow()
    if q.get('symbol')!='BTCUSDT': raise IntegrityError('Wrong spot symbol')
    observed=timely(q['closeTime'],now,180)
    price,low,high=[number(q[k],positive=True) for k in ('lastPrice','lowPrice','highPrice')]
    if not low<=price<=high: raise IntegrityError('Spot outside 24h range')
    return {'price':price,'change_24h_pct':number(q['priceChangePercent']),
            'low_24h':low,'high_24h':high,'source':evidence(r,observed)}


def collect_price_context():
    r=get(SPOT+'/api/v3/klines',{'symbol':'BTCUSDT','interval':'1d','limit':401})
    d=parse_klines(r.json(),'1d',utcnow())
    if len(d)<366: raise IntegrityError('Insufficient daily indicator history')
    returns=np.log(d.close).diff().dropna(); vol=float(returns.tail(20).std(ddof=1)*math.sqrt(365))
    return {'rv20':vol,'close':float(d.close.iloc[-1]),'ma50':float(d.close.tail(50).mean()),
            'ma200':float(d.close.tail(200).mean()),
            'return_30d_pct':float((d.close.iloc[-1]/d.close.iloc[-31]-1)*100),
            'low_20d':float(d.low.tail(20).min()),'high_20d':float(d.high.tail(20).max()),
            'source':evidence(r,(d.time.iloc[-1]+pd.Timedelta(days=1)).isoformat())}


def collect_spot_flow():
    r=get(SPOT+'/api/v3/klines',{'symbol':'BTCUSDT','interval':'1h','limit':26})
    d=parse_klines(r.json(),'1h',utcnow()).tail(24)
    if len(d)!=24:raise IntegrityError('Need 24 complete hourly flow bars')
    total,buy=float(d.quote.sum()),float(d.buy.sum());sell=total-buy
    if total<=0 or sell<=0:raise IntegrityError('Undefined taker ratio')
    return {'buy_sell_ratio':buy/sell,'imbalance':(buy-sell)/total,
            'source':evidence(r,(d.time.iloc[-1]+pd.Timedelta(hours=1)).isoformat())}


def collect_oi():
    r=get(FUTURES+'/fapi/v1/openInterest',{'symbol':'BTCUSDT'});q=r.json()
    if q.get('symbol')!='BTCUSDT':raise IntegrityError('Wrong OI symbol')
    return {'oi_btc':number(q['openInterest'],positive=True),
            'source':evidence(r,timely(q['time'],utcnow(),600))}


def collect_funding():
    r=get(FUTURES+'/fapi/v1/fundingRate',{'symbol':'BTCUSDT','limit':2});rows=r.json();now=utcnow()
    if not isinstance(rows,list) or not rows:raise IntegrityError('Empty funding history')
    if any(x.get('symbol')!='BTCUSDT' for x in rows):raise IntegrityError('Wrong funding symbol')
    q=max(rows,key=lambda x:int(x['fundingTime']))
    return {'last_completed_rate':number(q['fundingRate']),
            'source':evidence(r,timely(q['fundingTime'],now,10*3600))}


def collect_futures_flow():
    r=get(FUTURES+'/futures/data/takerlongshortRatio',{'symbol':'BTCUSDT','period':'1h','limit':24});rows=r.json()
    if not isinstance(rows,list) or len(rows)!=24:raise IntegrityError('Incomplete futures taker history')
    stamps=[int(x['timestamp']) for x in rows]
    if len(set(stamps))!=24 or any(b-a!=3600000 for a,b in zip(stamps,stamps[1:])):
        raise IntegrityError('Futures flow calendar gap')
    buys=[number(x['buyVol']) for x in rows];sells=[number(x['sellVol']) for x in rows]
    if min(buys+sells)<0:raise IntegrityError('Negative futures volume')
    buy=sum(buys);sell=sum(sells)
    if min(buy,sell)<=0:raise IntegrityError('Invalid futures taker volume')
    return {'buy_sell_ratio':buy/sell,'source':evidence(r,timely(stamps[-1],utcnow(),2*3600))}


class TableRows(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        if tag=='tr' and self.row is not None:
            self.rows.append(self.row);self.row=None


def flow_number(text):
    s=text.strip().replace(',','').replace('\u2212','-')
    if s in ('','-','—','–','N/A'):return None
    if s.startswith('(') and s.endswith(')'):s='-'+s[1:-1]
    return number(s)


def parse_etf(text,now):
    parser=TableRows();parser.feed(text);dated={};width=None
    for row in parser.rows:
        if row and row[-1].strip().lower()=='total':width=len(row)
        if not row or not re.fullmatch(r'\d{1,2} [A-Za-z]{3} \d{4}',row[0]):continue
        if width is None or len(row)!=width or len(row)<10:raise IntegrityError('Unknown ETF table width/header')
        date=pd.Timestamp(datetime.strptime(row[0],'%d %b %Y'),tz='UTC')
        if date>now.normalize():raise IntegrityError('Future ETF observation')
        values=[flow_number(x) for x in row[1:]]
        complete=all(x is not None for x in values)
        if complete and abs(sum(values[:-1])-values[-1])>0.11*len(values):
            raise IntegrityError('ETF total does not reconcile with funds')
        result={'date':str(date.date()),'total_usdm':values[-1] if complete else None,'complete':complete}
        if date in dated and dated[date]!=result:raise IntegrityError('Conflicting duplicate ETF rows')
        dated[date]=result
    rows=[dated[k] for k in sorted(dated)]
    done=[i for i,x in enumerate(rows) if x['complete']]
    if not done:raise IntegrityError('No complete ETF sessions')
    last=done[-1];latest=rows[last]
    if (now.normalize()-pd.Timestamp(latest['date'],tz='UTC')).days>5:raise IntegrityError('Stale ETF table')
    def window(n):
        part=rows[max(0,last+1-n):last+1]
        return sum(x['total_usdm'] for x in part) if len(part)==n and all(x['complete'] for x in part) else None
    return {'latest':latest,'sum3_usdm':window(3),'sum5_usdm':window(5),'sum20_usdm':window(20),
            'partial_sessions':[x['date'] for x in rows if not x['complete']]}


def collect_etf():
    r=get(ETF);data=parse_etf(r.text,utcnow());return data|{'source':evidence(r,data['latest']['date'])}


def parse_fred(text,sid,now):
    reader=csv.DictReader(io.StringIO(text));fields=reader.fieldnames or []
    dates=[x for x in fields if x.lower() in ('date','observation_date')]
    if len(dates)!=1 or sid not in fields:raise IntegrityError(f'Unknown FRED CSV schema for {sid}')
    seen=set();observations=[]
    for row in reader:
        day=row[dates[0]]
        if day in seen:raise IntegrityError('Duplicate FRED date')
        seen.add(day);dt=pd.Timestamp(day,tz='UTC')
        if dt>now.normalize():raise IntegrityError('Future FRED date')
        if row[sid] in ('','.'):continue
        value=number(row[sid]);observations.append((dt,row[sid],value))
    if not observations:raise IntegrityError('No FRED observations')
    observations.sort();dt,exact,value=observations[-1]
    max_age=75 if sid in ('M2SL','CPIAUCSL','UNRATE','PAYEMS') else (14 if sid in ('WALCL','WTREGEN') else 7)
    if (now.normalize()-dt).days>max_age:raise IntegrityError(f'Stale FRED series {sid}')
    past=[x for x in observations if x[0]<=dt-pd.Timedelta(days=91)]
    return {'series_id':sid,'value':exact,'observation_date':str(dt.date()),
            'delta_13w':value-past[-1][2] if past else None,
            'source_url':f'https://fred.stlouisfed.org/series/{sid}'}


def collect_fred(sid):
    now=utcnow();r=get('https://fred.stlouisfed.org/graph/graph.csv',{'id':sid,'cosd':str((now-pd.Timedelta(days=500)).date())})
    data=parse_fred(r.text,sid,now)
    return data|{'source':evidence(r,data['observation_date'])}


def capture_preclose(feeds,now,path=shadow.PRECLOSE_PATH):
    """No past packet fabrication. Existing packets are byte-for-byte preserved."""
    if now.weekday()!=0 or now.hour<20:return 'NOT_IN_MONDAY_CAPTURE_WINDOW'
    old=pd.read_csv(path,dtype=str,keep_default_na=False) if path.exists() and path.stat().st_size else pd.DataFrame()
    origin=str(now.date())
    if not old.empty and origin in set(old.origin_date):
        validate_packet(old,now.normalize(),shadow.SERIES,now=now);return 'ALREADY_CAPTURED_IMMUTABLE'
    rows=[]
    for sid in shadow.SERIES:
        item=feeds.get('fred_'+sid,{})
        if item.get('status')!='OK':return 'INCOMPLETE_PACKET_NOT_WRITTEN'
        capture=pd.Timestamp(item['source']['retrieved_at_utc'])
        if capture.normalize()!=now.normalize() or capture>now:return 'CAPTURE_CLOCK_MISMATCH'
        url=item['source_url'];value=item['value'];obs=item['observation_date']
        rows.append({'origin_date':origin,'capture_time_utc':capture.isoformat(),
                     'target_btc_close_time_utc':(now.normalize()+pd.Timedelta(days=1)).isoformat(),
                     'series_id':sid,'value':value,'observation_date':obs,
                     'source_sha256':observation_hash(sid,obs,value,url),'source_url':url})
    new=pd.DataFrame(rows);validate_packet(new,now.normalize(),shadow.SERIES,now=now)
    path.parent.mkdir(parents=True,exist_ok=True)
    header=not path.exists() or not path.stat().st_size
    with path.open('a',encoding='utf-8',newline='') as f:new.to_csv(f,index=False,header=header)
    return 'COMPLETE_PACKET_CAPTURED_BEFORE_CLOSE'


def frozen_outlook(path=Path('shadow/forecasts.csv')):
    f=pd.read_csv(path);validate_forecasts(f)
    if f.empty:raise IntegrityError('No frozen forecast records')
    origin=max(f.origin_date.astype(str));g=f[f.origin_date.astype(str)==origin]
    return {'origin':origin,'rows':g.drop(columns=['p_up'],errors='ignore').fillna('').to_dict('records')}


def ranges(price,annual_vol):
    if not math.isfinite(annual_vol) or annual_vol<=0:raise IntegrityError('Invalid volatility')
    return {h:[price*math.exp(-annual_vol*math.sqrt(h/365)),price*math.exp(annual_vol*math.sqrt(h/365))] for h in (7,30,90)}


def describe(feeds):
    """Transparent descriptive conditions, never a fitted probability or trade call."""
    etf,flow=feeds.get('etf',{}),feeds.get('spot_flow',{})
    if etf.get('status')!='OK' or flow.get('status')!='OK':
        return 'НЕДОСТАТОЧНО ДАННЫХ','Нет полного сочетания ETF-потоков и спотового taker flow; направление не назначено.'
    e=etf.get('sum3_usdm');ratio=flow['buy_sell_ratio']
    if e is None:return 'НЕДОСТАТОЧНО ДАННЫХ','Не хватает трёх полностью опубликованных ETF-сессий.'
    if e>0 and ratio>1:return 'СПРОС ПОДДЕРЖИВАЕТ','ETF за 3 сессии положительны; в 24 закрытых часах спотовые taker-покупки превышают продажи. Не торговый сигнал.'
    if e<0 and ratio<1:return 'ДАВЛЕНИЕ ПРОДАЖ','ETF за 3 сессии отрицательны; спотовый taker flow направлен в продажи. Не торговый сигнал.'
    return 'ПРОТИВОРЕЧИВЫЕ ПОТОКИ','Направления ETF за 3 сессии и спотового taker flow расходятся. Доказанного преимущества для сделки нет.'


def report_rows(feeds,now,meta):
    rows=[['Блок','Показатель','Значение','На дату UTC','Статус / смысл','Источник']]
    def add(block,label,value='',asof='',status='',source=''):
        rows.append([block,label,value,asof,status,source])
    local_expiry=(now+pd.Timedelta(hours=TTL_HOURS)).tz_convert('America/Merida').tz_localize(None)
    serial=(local_expiry-pd.Timestamp('1899-12-30')).total_seconds()/86400
    add('Система','expiry_merida_serial',serial)
    add('Система','Обновление UTC',now.strftime('%Y-%m-%d %H:%M:%S'))
    add('Система','Состояние источников',meta['health'],status='OK ≠ доказанная точность модели',source=meta['run_url'])
    add('Решение','Допуск к торговому сигналу','ABSTAIN',status='Преимущество не доказано; вес экспериментальных моделей = 0. Автоторговли нет.')
    bias,why=describe(feeds);add('Обзор','Состояние потоков',bias,status=why)
    spot=feeds.get('spot',{});context=feeds.get('price_context',{})
    def source(item):return item.get('source',{}).get('url','')
    def observed(item):return item.get('source',{}).get('observed_at_utc','') or ''
    if spot.get('status')=='OK':
        add('Рынок','BTCUSDT, USDT',round(spot['price'],2),observed(spot),'Текущая котировка Binance; не USD',source(spot))
        add('Рынок','Изменение за 24 часа',f"{spot['change_24h_pct']:+.2f}%",observed(spot),'Факт, не прогноз',source(spot))
        add('Рынок','Диапазон за 24 часа',f"{spot['low_24h']:,.2f} – {spot['high_24h']:,.2f}",observed(spot),'USDT',source(spot))
    else:add('Рынок','BTCUSDT','НЕТ ДАННЫХ',status=spot.get('error','UNAVAILABLE'))
    if context.get('status')=='OK':
        add('Рынок','MA50 / MA200',f"{context['ma50']:,.0f} / {context['ma200']:,.0f}",observed(context),'Только закрытые дневные свечи; не сигнал',source(context))
        add('Риск','Реализованная волатильность 20 дней',f"{context['rv20']*100:.1f}% годовых",observed(context),'Описательная оценка, не прогноз вероятности',source(context))
        if spot.get('status')=='OK':
            for h,(lo,hi) in ranges(spot['price'],context['rv20']).items():
                add('Риск',f'{h} дней: масштаб ±1σ',f'{lo:,.0f} – {hi:,.0f}',now.isoformat(),'USDT; нулевой дрейф и постоянная волатильность. Не целевая цена и не калиброванный интервал.',source(context))
    for key,label,field,fmt in [('spot_flow','Спотовый taker buy/sell, 24 закрытых часа','buy_sell_ratio','{:.3f}'),('futures_flow','Фьючерсный taker buy/sell, 24 часа','buy_sell_ratio','{:.3f}'),('oi','Открытый интерес, BTC','oi_btc','{:,.2f}'),('funding','Последний завершённый funding','last_completed_rate','{:.6%}')]:
        item=feeds.get(key,{})
        add('Потоки',label,fmt.format(item[field]) if item.get('status')=='OK' else 'НЕТ ДАННЫХ',observed(item),('Проверено; не заменяется другим рынком' if item.get('status')=='OK' else item.get('error','UNAVAILABLE')),source(item))
    etf=feeds.get('etf',{})
    if etf.get('status')=='OK':
        add('ETF','Последняя полная сессия, млн USD',etf['latest']['total_usdm'],etf['latest']['date'],'Только полностью заполненные фонды; частичный нулевой total не считается нулевым потоком',source(etf))
        for n in (3,5,20):
            v=etf.get(f'sum{n}_usdm');add('ETF',f'Сумма за {n} сессий, млн USD',round(v,2) if v is not None else 'НЕТ ДАННЫХ',etf['latest']['date'],'Без замены пропусков нулём',source(etf))
        add('ETF','Неполные сессии',', '.join(etf['partial_sessions']) or 'Нет',status='Исключены из итогов, пока не опубликованы все фонды',source=source(etf))
    else:add('ETF','Данные Farside','НЕТ ДАННЫХ',status=etf.get('error','UNAVAILABLE'),source=ETF)
    for sid,label in [('WALCL','Активы ФРС, млн USD'),('WTREGEN','TGA, млн USD'),('RRPONTSYD','RRP, млрд USD'),('DFII10','Реальная доходность 10Y, %'),('DTWEXBGS','Широкий индекс USD'),('VIXCLS','VIX'),('M2SL','M2, млрд USD'),('UNRATE','Безработица, %')]:
        item=feeds.get('fred_'+sid,{})
        add('Макро',label,item.get('value','НЕТ ДАННЫХ'),item.get('observation_date',''),('Последний опубликованный срез; не синхронная оценка глобальной ликвидности' if item.get('status')=='OK' else item.get('error','UNAVAILABLE')),item.get('source_url',f'https://fred.stlouisfed.org/series/{sid}'))
    outlook=feeds.get('outlook',{})
    if outlook.get('status')=='OK':
        add('Модели','Зафиксированный прогноз',outlook['origin'],status='ЭКСПЕРИМЕНТ: старый исходный день и исходные цены сохранены; не пересчитаны от текущего рынка.')
        for h in (7,30,90,180,365):
            group=[x for x in outlook['rows'] if int(x['horizon_days'])==h];vals={x['model']:x for x in group}
            a=vals['primary_equal_weight_ensemble'];b=vals['price_ridge'];c=vals['price_macro_ridge']
            due=pd.Timestamp(a['due_date'],tz='UTC')+pd.Timedelta(days=1)
            note='ЭКСПЕРИМЕНТ, вес 0' if now<due else 'Горизонт истёк; не текущий сигнал'
            add('Модели',f'{h}д: базовая / цена / цена+макро',f"{a['forecast_price']:,.0f} / {b['forecast_price']:,.0f} / {c['forecast_price']:,.0f}",a['due_date'],note+'; USDT, закрытие указанного дня UTC',REPO+'/blob/main/shadow/forecasts.csv')
    else:add('Модели','Прогноз','НЕТ ДАННЫХ',status=outlook.get('error','UNAVAILABLE'))
    add('Проверки','Предварительный макропакет',meta['preclose_status'],status='Автосбор в понедельник после 20:00 UTC; полный пакет должен быть сохранён до закрытия дня.')
    last=meta.get('shadow',{});add('Проверки','Последний запуск недельной модели',last.get('run_capture_utc','НЕТ ДАННЫХ'),status=f"Последний исходный день: {last.get('origin_date','?')}",source=REPO+'/blob/main/shadow/last_run.json')
    issued=meta.get('issued',{});add('Проверки','Чистые будущие исходы',issued.get('completed_rows',0),status='Считаются только прогнозы, опубликованные до начала оцениваемого интервала.',source=REPO+'/blob/main/shadow/issued_status.json')
    add('Ограничения','Не подключено','Истинная карта ликвидаций; ончейн-потоки; Coinbase premium',status='Не выводятся из стакана, OI или движения цены.')
    add('Ограничения','Вероятность роста / доходность стратегии','НЕ ДОКАЗАНЫ',status='2024–2025 уже просмотрены. Технический PASS не означает статистическое преимущество.')
    add('Система','Версия кода',meta['code_sha'],status='Каждый опубликованный срез сохраняется в истории Git.',source=meta['run_url'])
    add('Система','Обновление отчёта','Каждый час, минута 23 UTC',status='Google IMPORTDATA обновляется отдельно, примерно раз в час. Верхний индикатор обнаруживает просроченный срез.')
    return rows


def atomic(path,text):
    path.parent.mkdir(exist_ok=True,parents=True);tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(text,encoding='utf-8');tmp.replace(path)


def csv_text(rows):
    stream=io.StringIO(newline='');w=csv.writer(stream)
    for row in rows:
        w.writerow(["'"+x if isinstance(x,str) and x.startswith(('=','+','@','\t','\r')) else x for x in row])
    return stream.getvalue()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--capture-preclose',action='store_true');args=ap.parse_args()
    check_runtime_contract();AUDIT.mkdir(exist_ok=True)
    jobs={'spot':collect_spot,'price_context':collect_price_context,'spot_flow':collect_spot_flow,
          'oi':collect_oi,'funding':collect_funding,'futures_flow':collect_futures_flow,'etf':collect_etf,'outlook':frozen_outlook}
    jobs.update({'fred_'+sid:(lambda sid=sid:collect_fred(sid)) for sid in shadow.SERIES})
    with ThreadPoolExecutor(max_workers=6) as pool:
        feeds=dict(pool.map(lambda pair:safe(*pair),jobs.items()))
    now=utcnow();required=('spot','price_context','spot_flow','outlook')
    failed=[k for k in required if feeds[k]['status']!='OK']
    health='DATA_FAILURE' if failed else ('PARTIAL' if any(x['status']!='OK' for x in feeds.values()) else 'OK')
    preclose=capture_preclose(feeds,now) if args.capture_preclose else 'PREVIEW_NO_STATE_WRITE'
    meta={'health':health,'critical_failures':failed,'generated_at_utc':now.isoformat(),
          'code_sha':os.getenv('GITHUB_SHA','LOCAL_TEST'),'run_url':REPO+'/actions/runs/'+os.getenv('GITHUB_RUN_ID','local'),
          'preclose_status':preclose,'decision':'ABSTAIN','auto_trading':False,'decision_weight':0}
    for key,path in [('shadow',Path('shadow/last_run.json')),('issued',Path('shadow/issued_status.json'))]:
        if path.exists():meta[key]=json.loads(path.read_text())
    rows=report_rows(feeds,now,meta);text=csv_text(rows)
    meta['report_sha256']=digest(text.encode());meta['sources']=feeds
    atomic(OUT/'report.csv',text);atomic(OUT/'status.json',json.dumps(meta,ensure_ascii=False,indent=2,allow_nan=False))
    if digest((OUT/'report.csv').read_bytes())!=meta['report_sha256']:raise IntegrityError('Report read-back hash mismatch')
    if len(list(csv.reader(io.StringIO(text))))!=len(rows):raise IntegrityError('CSV row-count mismatch')
    print(json.dumps({k:v for k,v in meta.items() if k not in ('sources','shadow','issued')},ensure_ascii=False,indent=2))
    for name,item in feeds.items():print(name,item['status'],item.get('error',''))

if __name__=='__main__':main()
