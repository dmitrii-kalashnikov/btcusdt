"""Production entry point: verified sources, conditional outlook, no promotion.
Market rules below are transparent EXPERIMENTAL descriptions, not fitted models.

USER-FACING PRESENTATION CONTRACT:
The ONLY visible BTC report is existing Google Sheet BTC FINAL REPORT, A1:D28.
It presents the working view, 7/30/90-day conditional scenarios, separately named
volatility risk scales, concise macro/flow interpretation and revision triggers.
The existing A100:F189 import and H250:L285 lookups are hidden implementation
ranges on the SAME tab. report.csv remains the wire format, not a second report.
Preserve its semantic label keys: the visible summary looks up labels, not row
positions. Never replace the compact view with logs, hashes, CI results, raw
model outputs or the experiment ledger. One confidence line communicates the
unproven predictive edge. Source dates and a two-hour stale guard remain visible.
This presentation change does not change algorithms, thresholds or promotion.
"""
from __future__ import annotations
import json,re,time
from datetime import datetime
from pathlib import Path
import pandas as pd
import requests
import btc_production as app
import btc_transport as transport
from btc_validation.core import IntegrityError

BASE_REPORT=app.report_rows
BASE_FRED=transport.parse_fred_page
BASE_CAPTURE=app.capture_preclose
BASE_READER=transport.reader


def reader_with_retry(url):
    """Retry transient transport faults only; no source substitution or stale fill."""
    # Run 33943564117 exposed a transient PAYEMS Reader HTTP 503. Keep the failure
    # in Actions, preserve all source validators, and retry the SAME source only.
    for attempt in range(3):
        try:
            return BASE_READER(url)
        except requests.RequestException as exc:
            response = getattr(exc, 'response', None)
            status = getattr(response, 'status_code', None)
            transient = status in (429, 500, 502, 503, 504) or isinstance(
                exc, (requests.Timeout, requests.ConnectionError))
            if not transient or attempt == 2:
                raise
            wait = float(2 ** (attempt + 1))
            retry_after = response.headers.get('Retry-After') if response is not None else None
            if retry_after is not None:
                try:
                    required_wait = float(retry_after)
                except (TypeError, ValueError):
                    raise exc
                if not 0 <= required_wait <= 60:
                    raise exc
                wait = max(wait, required_wait)
            time.sleep(wait)
    raise AssertionError('unreachable')


def fred_with_change(text,sid,now):
    result=BASE_FRED(text,sid,now)
    pattern=r'^\s*(?:\|\s*)?(\d{4}-\d{2}-\d{2}|[A-Z][a-z]{2} \d{4}):?\s*(?:\|\s*)?([-+]?\d[\d,]*(?:\.\d+)?)\s*(?:\||$)'
    observations={}
    for line in text.replace('*','').splitlines():
        match=re.match(pattern,line)
        if not match:continue
        day,value=match.groups()
        if not day[0].isdigit():day=datetime.strptime(day,'%b %Y').strftime('%Y-%m-01')
        observations[day]=value.replace(',','')
    earlier=sorted(d for d in observations if d<result['observation_date'])
    result.update(previous_date=earlier[-1] if earlier else None,change_previous=None)
    if earlier:result['change_previous']=app.number(result['value'])-app.number(observations[earlier[-1]])
    return result


def capture_at_contract_time(feeds,now,path=app.shadow.PRECLOSE_PATH):
    # Original Monday 16:30 Merida capture remains authoritative. The hourly
    # worker is only an idempotent fallback AFTER that time, never an early packet.
    if now.weekday()!=0 or now.hour*60+now.minute<22*60+30:
        return 'NOT_IN_MONDAY_CAPTURE_WINDOW'
    return BASE_CAPTURE(feeds,now,path)


def render(feeds,now,meta):
    rows=BASE_REPORT(feeds,now,meta)
    spot,context=feeds.get('spot',{}),feeds.get('price_context',{})
    extra=[]
    def add(label,value,meaning):extra.append(['Сценарии',label,value,now.isoformat(),meaning,''])
    if spot.get('status')=='OK' and context.get('status')=='OK':
        lo,hi=context['low_20d'],context['high_20d']
        add('PRIMARY — условный рабочий сценарий',f'Наблюдение в границах {lo:,.0f}–{hi:,.0f} USDT; 1–7 дней',
            'Границы — минимум/максимум 20 закрытых суток. Это не обещание удержания диапазона. Без подтверждения потоками направление не назначается.')
        add('SECONDARY — условие усиления спроса',f'Закрытие дня выше {hi:,.0f}; 7–30 дней',
            'Дополнительно ETF 3D и 5D > 0 и спотовый taker buy/sell > 1. Экспериментальная гипотеза; вес решения 0.')
        add('TAIL — условие ухудшения',f'Закрытие дня ниже {lo:,.0f}; 1–30 дней',
            'Дополнительно ETF 3D < 0 и спотовый taker buy/sell < 1. Метки сценариев не являются вероятностями или доказанным ранжированием.')
    else:add('Текущие ценовые сценарии','НЕТ ДАННЫХ','Критический источник цены отсутствует; старые уровни не используются.')
    # Near the top, but after the immutable health/expiry rows.
    rows[6:6]=extra
    for sid,label in [('DFF','Эффективная ставка ФРС, %'),('DGS2','Доходность 2Y, %'),('DGS10','Доходность 10Y, %'),('NASDAQCOM','Nasdaq Composite'),('CPIAUCSL','CPI, индекс'),('PAYEMS','Занятость, тысяч человек')]:
        item=feeds.get('fred_'+sid,{})
        rows.append(['Макро',label,item.get('value','НЕТ ДАННЫХ'),item.get('observation_date',''),
                     'Последний опубликованный срез; не прогноз.',item.get('source_url','')])
    for row in rows:
        if row[0]=='Макро':
            sid=row[5].rsplit('/',1)[-1];item=feeds.get('fred_'+sid,{})
            delta=item.get('change_previous')
            if delta is not None:row[4]=f"Изменение {delta:+.6g} с {item['previous_date']} в единицах ряда. Периоды рядов различаются; не синхронная глобальная ликвидность."
        if row[1]=='Обновление отчёта':
            row[4]='GitHub собирает ежечасно; Google IMPORTDATA проверяет изменения раз в час при открытом документе. Нет гарантии обновления закрытой таблицы.'
    evidence_path=Path('btc_validation/RELEASE_EVIDENCE.json')
    if evidence_path.exists():
        evidence=json.loads(evidence_path.read_text())
        for label in evidence['findings']:
            rows.append(['Валидация','Исторический результат',label,'2022–2025',
                         'Повторный расчёт ранее просмотренных данных; не новый holdout. DECISION-GRADE отсутствует.',app.REPO+'/blob/main/EXPERIMENT_LEDGER.md'])
    return rows


def record_release(path=Path('EXPERIMENT_LEDGER.md'), evidence_path=Path('btc_validation/RELEASE_EVIDENCE.json')):
    evidence=json.loads(evidence_path.read_text())
    marker=evidence['ledger_marker'];old=path.read_text()
    if marker not in old:
        path.write_text(old+'\n'+evidence['ledger_entry']+'\n')


def install():
    transport.reader=reader_with_retry
    transport.parse_fred_page=fred_with_change
    app.report_rows=render
    app.capture_preclose=capture_at_contract_time

if __name__=='__main__':
    install()
    transport.main()
    record_release()
