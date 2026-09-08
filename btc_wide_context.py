"""Unfitted broad-market measurements. NEVER a model, trading score or promotion input.

Current-vintage FRED history is descriptive only. The existing 14-row PIT packet,
models and immutable forecasts are not modified. Errors stay visible per source.
"""
from __future__ import annotations
import csv, io, json, math, re, statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

# label, units, maximum observation age in calendar days; NOT predictive thresholds.
SERIES = {
 'WRESBAL': ('Банковские резервы США', 'млн USD', 14),
 'SOFR': ('Стоимость краткосрочного обеспеченного кредита', '%', 7),
 'IORB': ('Процент ФРС на банковские резервы', '%', 7),
 'NFCI': ('Финансовые условия США', 'индекс', 18),
 'ANFCI': ('Финансовые условия с поправкой на экономику', 'индекс', 18),
 'T10YIE': ('Инфляционная компенсация в облигациях', '%', 7),
 'DCOILWTICO': ('Нефть WTI', 'USD/баррель', 10),
 'DEXJPUS': ('Доллар к иене', 'JPY/USD', 18),
 'SP500': ('Рынок акций США', 'индекс', 7),
}
CONTEXT_LIMITATIONS = (
 'Это наблюдения, не проверенные предсказатели. Банковские резервы не равны всем деньгам в экономике. '
 'Снижение резервов не доказывает банковский кризис; нефть и иена не имеют постоянного знака влияния на BTC. '
 'Новые ряды не входят в исходный пакет из 14 макропоказателей.'
)


def utc(value):
    t = datetime.fromisoformat(str(value).replace('Z', '+00:00')) if not isinstance(value, datetime) else value
    if t.tzinfo is None: raise ValueError('Timestamp must have timezone')
    return t.astimezone(timezone.utc)


def parse_history(text, sid, now):
    if sid not in SERIES: raise ValueError('Unregistered context series')
    rows = csv.DictReader(io.StringIO(text))
    fields = rows.fieldnames or []
    if len(fields) != 2 or fields[1] != sid or fields[0] not in ('DATE','observation_date'):
        raise ValueError('FRED CSV identity/schema mismatch')
    out = []; seen = set(); today = utc(now).date(); previous_day = None
    for r in rows:
        d = date.fromisoformat(r[fields[0]])
        if d > today: raise ValueError('Future observation')
        if d in seen: raise ValueError('Duplicate observation')
        if previous_day is not None and d <= previous_day: raise ValueError('Unordered calendar')
        previous_day = d
        seen.add(d)
        if r[sid] in ('', '.'): continue
        v = float(r[sid])
        if not math.isfinite(v): raise ValueError('Nonfinite measurement')
        if out and d <= out[-1][0]: raise ValueError('Unordered history')
        out.append((d, v))
    if not out: raise ValueError('No observations')
    if (today-out[-1][0]).days > SERIES[sid][2]: raise ValueError('Stale context series')
    return out


def summarize(history):
    d, v = history[-1]
    result = {'observation_date': d.isoformat(), 'value': v, 'n': len(history),
              'change_previous': v-history[-2][1] if len(history)>1 else None,
              'previous_date': history[-2][0].isoformat() if len(history)>1 else None,
              'windows': {}, 'z_prior_60_observations': None}
    for n in (4,13,20,60):
        if len(history)>n:
            bd,bv=history[-n-1]
            result['windows'][str(n)]={'from':bd.isoformat(),'to':d.isoformat(),'change':v-bv}
    prior=[x[1] for x in history[-61:-1]]
    if len(prior)==60 and statistics.stdev(prior)>0:
        result['z_prior_60_observations']=(v-statistics.mean(prior))/statistics.stdev(prior)
    return result


def aligned_rate_spread(left, right, now):
    a,b=dict(left),dict(right); common=sorted(set(a)&set(b))
    if not common: raise ValueError('No same-date rate pair')
    d=common[-1]
    if d > utc(now).date() or (utc(now).date()-d).days>7:
        raise ValueError('Stale/future paired rate date')
    return {'observation_date':d.isoformat(),'basis_points':100*(a[d]-b[d])}


def read_institution_packet(path, now):
    p=json.loads(Path(path).read_text()); now=utc(now)
    if p['schema']!='institution-context-v1' or p['decision_weight']!=0:
        raise ValueError('Institution contract mismatch')
    for e in p['events']:
        if not e['source_url'].startswith('https://www.sec.gov/Archives/edgar/data/1050446/'):
            raise ValueError('Unverified institution source')
        if utc(e['observed_by_agent_utc'])>now: raise ValueError('Future retrieval')
        filing = date.fromisoformat(e['filing_date'])
        if filing>now.date() or filing>utc(e['observed_by_agent_utc']).date(): raise ValueError('Future filing')
        if date.fromisoformat(e['period_end'])>filing: raise ValueError('Future event')
        # Never use transaction-period start as release/feature-availability time.
        e['available_at_utc']=e['observed_by_agent_utc']
        e['status']='DATED_DISCLOSURE' if (now.date()-date.fromisoformat(e['filing_date'])).days<=10 else 'STALE_DISCLOSURE'
    return p


def parse_page(text, sid, now):
    """Same official public FRED observation, not a substitute dataset or vintage."""
    url='https://fred.stlouisfed.org/series/'+sid
    if 'URL Source: '+url not in text: raise ValueError('Reader original URL mismatch')
    if re.search(r'Warning:.*(?:error|403|401|451)',text,re.I): raise ValueError('Origin access restriction')
    if f'({sid})' not in text and f'[{sid}]' not in text: raise ValueError('Page series identity mismatch')
    obs={}
    for line in text.replace('*','').splitlines():
        m=re.match(r'^\s*(?:\|\s*)?(\d{4}-\d{2}-\d{2}):?\s*(?:\|\s*)?([-+]?\d[\d,]*(?:\.\d+)?)\s*(?:\||$)',line)
        if m:
            d,v=m.groups();v=v.replace(',','')
            if d in obs and obs[d]!=v: raise ValueError('Conflicting official observations')
            obs[d]=v
    if not obs: raise ValueError('No exact official observation rows')
    return parse_history('DATE,'+sid+'\n'+'\n'.join(d+','+obs[d] for d in sorted(obs)),sid,now)


def collect(now, getter, evidence):
    """Current public-page capture; retains limited history rather than inventing it.

    The hosting transport already supports FRED public pages. Only these nine
    allowlisted public pages use Reader; restricted futures APIs are never relayed.
    """
    def one(sid):
        url='https://fred.stlouisfed.org/series/'+sid
        try:
            r=getter('https://r.jina.ai/'+url); h=parse_page(r.text,sid,now)
            return sid,{'status':'OK',**summarize(h),'history':[(d.isoformat(),v) for d,v in h],
                        'source':evidence(r,h[-1][0].isoformat()),'source_url':url,
                        'history_scope':'RECENT_OFFICIAL_PAGE_ROWS_ONLY',
                        'vintage_policy':'CURRENT_VINTAGE_CONTEXT_ONLY_NOT_HISTORICAL_PIT'}
        except Exception as exc:
            return sid,{'status':'UNAVAILABLE','error':(type(exc).__name__+': '+str(exc))[:350]}
    # Avoid exhausting a public source while the original 14-row capture runs.
    with ThreadPoolExecutor(max_workers=2) as pool: result=dict(pool.map(one,SERIES))
    a,b=result['SOFR'],result['IORB']
    if a['status']==b['status']=='OK':
        try:
            hist=lambda x:[(date.fromisoformat(d),v) for d,v in x['history']]
            result['SOFR_MINUS_IORB']={'status':'OK',**aligned_rate_spread(hist(a),hist(b),now)}
        except ValueError as exc: result['SOFR_MINUS_IORB']={'status':'UNAVAILABLE','error':str(exc)}
    else: result['SOFR_MINUS_IORB']={'status':'UNAVAILABLE','error':'Both same-date rate histories are required'}
    return result


def report_rows(data, packet, now):
    rows=[]
    for sid,(label,units,_) in SERIES.items():
        x=data.get(sid,{}); ok=x.get('status')=='OK'
        change=x.get('change_previous'); delta=f'; изменение {change:+.6g} {units} с {x.get("previous_date")}' if change is not None else ''
        meaning=('Последнее опубликованное значение'+delta+'. Не сигнал покупки/продажи.' if ok else x.get('error','Нет проверенного источника'))
        rows.append(['Широкий рынок',label,str(x['value'])+' '+units if ok else 'НЕТ ДАННЫХ',x.get('observation_date',''),meaning,'https://fred.stlouisfed.org/series/'+sid])
    pair=data.get('SOFR_MINUS_IORB',{}); ok=pair.get('status')=='OK'
    rows.append(['Широкий рынок','Стоимость фондирования относительно ставки ФРС',
                 f'{pair["basis_points"]:+.2f} базисного пункта' if ok else 'НЕТ СОПОСТАВИМЫХ ДАННЫХ',pair.get('observation_date',''),
                 'Сравнение только на одной дате; само по себе не доказывает дефицит денег или направление BTC.','https://www.newyorkfed.org/markets/reference-rates/sofr'])
    if packet.get('error'):
        rows.append(['Крупные держатели','Strategy: качество раскрытия','НЕТ ПРОВЕРЕННЫХ ДАННЫХ','',packet['error'],''])
    for e in packet.get('events',[]):
        rows.append(['Крупные держатели','Strategy: распределение капитала',e['summary_ru'],e['period_end'],
                     e['status']+'; опубликовано '+e['filing_date']+'. '+e['interpretation_ru'],e['source_url']])
    rows.append(['Широкий рынок','Полнота и пределы расширенного анализа',CONTEXT_LIMITATIONS,utc(now).isoformat(),
                 'НЕ ПОДКЛЮЧЕНЫ: глобальная денежная масса с историей публикаций, позиции банков/CME, опционы, проверенные потоки стейблкоинов, крупные продажи майнеров и государств. Это не нули.',''])
    return rows


def install():
    import btc_production as app
    previous=app.report_rows
    def render(feeds,now,meta):
        data=collect(now,app.get,app.evidence)
        try: packet=read_institution_packet('research/institution_context.json',now)
        except Exception as exc: packet={'events':[],'error':str(exc)}
        unavailable=[sid for sid,x in data.items() if x.get('status')!='OK']
        good=not unavailable and 'error' not in packet
        feeds['wide_context']={'status':'OK' if good else 'UNAVAILABLE','measurements':data,
                               'institution_packet':packet,'decision_weight':0}
        meta['context_unavailable']=unavailable+(['institution_packet'] if 'error' in packet else [])
        if not good and meta.get('health')=='OK': meta['health']='PARTIAL'
        # The old renderer, numerical model and semantic keys remain unchanged.
        rows=previous(feeds,now,meta)
        return rows+report_rows(data,packet,now)
    app.report_rows=render
