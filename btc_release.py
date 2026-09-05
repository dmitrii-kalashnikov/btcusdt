"""Production entry point: verified sources, conditional outlook, no promotion.
Market rules below are transparent EXPERIMENTAL descriptions, not fitted models.
"""
from __future__ import annotations
import json,re
from datetime import datetime
from pathlib import Path
import pandas as pd
import btc_production as app
import btc_transport as transport
from btc_validation.core import IntegrityError

BASE_REPORT=app.report_rows
BASE_FRED=transport.parse_fred_page
BASE_CAPTURE=app.capture_preclose


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
    transport.parse_fred_page=fred_with_change
    app.report_rows=render
    app.capture_preclose=capture_at_contract_time

if __name__=='__main__':
    install()
    transport.main()
    record_release()
