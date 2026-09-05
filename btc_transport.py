"""Public-page adapters; no model changes, paid APIs or access-control bypass.
Public FRED/Farside pages use basic keyless Reader. Restricted live futures APIs
are never relayed; unrestricted Vision archives are explicitly labelled delayed.
"""
from __future__ import annotations
import html,re,threading,time
from datetime import datetime
import pandas as pd
import requests
import btc_production as app
from btc_validation.collect import fetch_zip,metrics_day
from btc_validation.core import IntegrityError,parse_archive_csv,digest

_LOCK=threading.Lock();_LAST=0.0
READER='https://r.jina.ai/'
ETF_ALL='https://farside.co.uk/bitcoin-etf-flow-all-data/'


def reader(url):
    global _LAST
    allowed={f'https://fred.stlouisfed.org/series/{s}' for s in app.shadow.SERIES}|{ETF_ALL}
    if url not in allowed:raise IntegrityError('Reader URL is not allowlisted')
    with _LOCK:
        time.sleep(max(0,3.2-(time.monotonic()-_LAST)));_LAST=time.monotonic()
    headers={'User-Agent':'btc-public-page-reader/1.0','x-no-cache':'true'}
    if url.endswith('/DFF'):headers['x-respond-with']='markdown'
    r=requests.get(READER+url,timeout=(5,45),headers=headers)
    r.raise_for_status()
    if len(r.content)>2_000_000:raise IntegrityError('Oversized reader response')
    app.evidence(r)
    if 'URL Source: '+url not in r.text:raise IntegrityError('Reader original URL mismatch')
    if re.search(r'Warning:.*(?:error|403|401|451)',r.text,re.I):raise IntegrityError('Origin page denied access; not retried through another proxy')
    return r


def parse_fred_page(text,sid,now):
    if f'({sid})' not in text and f'[{sid}]' not in text:raise IntegrityError('FRED page series identity mismatch')
    observations={}
    pattern=r'^\s*(?:\|\s*)?(\d{4}-\d{2}-\d{2}|[A-Z][a-z]{2} \d{4}):?\s*(?:\|\s*)?([-+]?\d[\d,]*(?:\.\d+)?)\s*(?:\||$)'
    for line in text.replace('*','').splitlines():
        m=re.match(pattern,line)
        if not m:continue
        date,value=m.groups();value=value.replace(',','')
        date=(datetime.strptime(date,'%b %Y').strftime('%Y-%m-01') if not date[0].isdigit() else date)
        if date in observations and observations[date]!=value:raise IntegrityError('Conflicting FRED observations')
        observations[date]=value
    if not observations:raise IntegrityError('No exact FRED observation rows')
    # H.10 daily observations are released WEEKLY for the preceding business week.
    # https://www.federalreserve.gov/releases/h10/ (Monday/next business day).
    max_age=75 if sid in ('M2SL','CPIAUCSL','UNRATE','PAYEMS') else (14 if sid in ('WALCL','WTREGEN','DTWEXBGS') else 7)
    for date,value in observations.items():
        app.number(value)
        if pd.Timestamp(date,tz='UTC')>now.normalize():raise IntegrityError('Future FRED observation')
    date=max(observations);value=observations[date]
    if (now.normalize()-pd.Timestamp(date,tz='UTC')).days>max_age:raise IntegrityError(f'Stale FRED series {sid}')
    return {'series_id':sid,'value':value,'observation_date':date,'delta_13w':None,
            'source_url':f'https://fred.stlouisfed.org/series/{sid}'}


def collect_fred(sid):
    url=f'https://fred.stlouisfed.org/series/{sid}';r=reader(url)
    data=parse_fred_page(r.text,sid,app.utcnow())
    data['source']=app.evidence(r,data['observation_date'])|{'original_url':url,'transport':'PUBLIC_PAGE_READER','hash_scope':'reader_response_bytes_not_original_html'}
    return data


def parse_etf_page(text,now):
    rows=[]
    for line in text.replace('*','').splitlines():
        if not line.lstrip().startswith('|'):continue
        row=[x.strip() for x in line.strip().strip('|').split('|')]
        if row and re.fullmatch(r'\d{1,2} [A-Za-z]{3} \d{4}',row[0]):
            if len(row)!=14:raise IntegrityError('Unexpected ETF fund-count schema')
            rows.append(row)
    if not rows:
        cells=[x.strip() for x in re.split(r'[\t\r\n]+',text) if x.strip()]
        header=['Date','IBIT','FBTC','BITB','ARKB','BTCO','EZBC','BRRR','HODL','BTCW','MSBT','GBTC','BTC','Total']
        if not any(cells[i:i+14]==header for i in range(len(cells))):raise IntegrityError('ETF vertical header mismatch')
        for i,cell in enumerate(cells):
            if re.fullmatch(r'\d{1,2} [A-Za-z]{3} \d{4}',cell):
                values=cells[i+1:i+14]
                if len(values)!=13:raise IntegrityError('Truncated ETF vertical row')
                for value in values:app.flow_number(value)
                next_cell=cells[i+14] if i+14<len(cells) else ''
                if next_cell!='Total' and not re.fullmatch(r'\d{1,2} [A-Za-z]{3} \d{4}',next_cell):raise IntegrityError('ETF vertical row width mismatch')
                rows.append([cell]+values)
    if not rows:raise IntegrityError('No ETF date rows')
    text='<table><tr>'+('<th></th>'*13)+'<th>Total</th></tr>'+''.join('<tr>'+''.join('<td>'+html.escape(c)+'</td>' for c in row)+'</tr>' for row in rows)+'</table>'
    return app.parse_etf(text,now)


def collect_etf():
    r=reader(ETF_ALL);data=parse_etf_page(r.text,app.utcnow())
    return data|{'source':app.evidence(r,data['latest']['date'])|{'original_url':ETF_ALL,'transport':'PUBLIC_PAGE_READER','hash_scope':'reader_response_bytes_not_original_html'}}


def archive(kind):
    now=app.utcnow()
    for lag in (1,2):
        day=now.normalize()-pd.Timedelta(days=lag)
        tail=(f'metrics/BTCUSDT/BTCUSDT-metrics-{day.date()}.zip' if kind=='metrics' else f'klines/BTCUSDT/1d/BTCUSDT-1d-{day.date()}.zip')
        url='https://data.binance.vision/data/futures/um/daily/'+tail
        raw,manifest=fetch_zip(url)
        if raw is None:
            if manifest['status']=='ARCHIVE_NOT_AVAILABLE':continue
            raise IntegrityError(manifest.get('error','Archive transport failure'))
        app.AUDIT.mkdir(exist_ok=True);(app.AUDIT/(digest(raw)+'.raw')).write_bytes(raw)
        return day,raw,manifest
    raise IntegrityError('Latest two completed-day public archives not available')


def collect_oi():
    day,raw,manifest=archive('metrics');audit={};d=metrics_day(raw,day,audit)
    value=app.number(d['oi_btc'],positive=True)
    return {'oi_btc':value,'source':{'url':manifest['url'],'retrieved_at_utc':app.utcnow().isoformat(),'observed_at_utc':d['metrics_observed_at'].isoformat(),'sha256':manifest['csv_sha256'],'archive_sha256':manifest['sha256'],'mode':'DELAYED_PUBLIC_ARCHIVE'},'note':'Последний доступный дневной архив Binance; не live API. Время наблюдения указано отдельно.'}


def collect_futures_flow():
    day,raw,manifest=archive('klines');d=parse_archive_csv(raw,'klines')
    if len(d)!=1 or d.time.iloc[0]!=day:raise IntegrityError('Wrong futures archive day')
    total=app.number(d.quote_volume.iloc[0],positive=True);buy=app.number(d.taker_buy_quote.iloc[0]);sell=total-buy
    if buy<0 or sell<=0:raise IntegrityError('Impossible futures archive volumes')
    return {'buy_sell_ratio':buy/sell,'source':{'url':manifest['url'],'retrieved_at_utc':app.utcnow().isoformat(),'observed_at_utc':(day+pd.Timedelta(days=1)).isoformat(),'sha256':manifest['csv_sha256'],'archive_sha256':manifest['sha256'],'mode':'DELAYED_PUBLIC_ARCHIVE'},'note':'Последние полные сутки из доступного архива, не скользящие 24 часа live API.'}


def funding_unavailable():
    raise IntegrityError('Live Binance futures API returns HTTP 451 on hosting. Access restriction respected; no proxy, substitute venue or invented funding rate.')


def main():
    app.collect_fred=collect_fred;app.collect_etf=collect_etf
    app.collect_oi=collect_oi;app.collect_futures_flow=collect_futures_flow;app.collect_funding=funding_unavailable
    original=app.report_rows
    def render(feeds,now,meta):
        required=('spot','price_context','spot_flow','outlook','etf')+tuple('fred_'+sid for sid in app.shadow.SERIES)
        meta['critical_failures']=[k for k in required if feeds.get(k,{}).get('status')!='OK']
        if meta['critical_failures']:meta['health']='DATA_FAILURE'
        rows=original(feeds,now,meta)
        for row in rows:
            if row[1]=='Открытый интерес, BTC' and feeds.get('oi',{}).get('status')=='OK':
                row[1]='Открытый интерес из дневного архива, BTC';row[4]=feeds['oi']['note']
            if row[1]=='Фьючерсный taker buy/sell, 24 часа' and feeds.get('futures_flow',{}).get('status')=='OK':
                row[1]='Фьючерсный taker buy/sell, архив суток';row[4]=feeds['futures_flow']['note']
            if row[1]=='Неполные сессии':
                row[1]='Неполные ETF-сессии за 30 дней'
                row[2]=', '.join(d for d in feeds.get('etf',{}).get('partial_sessions',[]) if pd.Timestamp(d,tz='UTC')>=now.normalize()-pd.Timedelta(days=30)) or 'Нет'
            if row[0] in ('ETF','Макро') and row[2]!='НЕТ ДАННЫХ':
                row[4]+=' | Публичная страница через Reader; даты источника сохранены.'
        return rows
    app.report_rows=render;app.main()

if __name__=='__main__':main()
