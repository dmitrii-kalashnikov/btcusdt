from __future__ import annotations
import math
from datetime import datetime,timezone
import numpy as np
import pandas as pd

def mature(f,daily):
    from btc_validation.core import validate_daily
    from btc_validation.runtime import validate_forecasts
    validate_forecasts(f)
    p=validate_daily(daily);p=p[p.time+pd.Timedelta(days=1)<=pd.Timestamp.now(tz='UTC')];p['date']=pd.to_datetime(p.time,utc=True).dt.strftime('%Y-%m-%d');closes=dict(zip(p.date,p.close.astype(float)))
    for i,r in f.iterrows():
        if str(r.get('status'))=='COMPLETE':continue
        due=str(r.due_date)[:10]
        if due not in closes:continue
        actual=float(closes[due]);lr=math.log(actual/float(r.spot));f.at[i,'actual_price']=actual;f.at[i,'actual_log_return']=lr;f.at[i,'actual_up']=float(lr>0);f.at[i,'status']='COMPLETE'
    return f

def stats(g):
    pred=pd.to_numeric(g.predicted_log_return);act=pd.to_numeric(g.actual_log_return);pup=pd.to_numeric(g.p_up);aup=pd.to_numeric(g.actual_up);e=pred-act
    return {'n':len(g),'directional_accuracy':float((np.sign(pred)==np.sign(act)).mean()),'mae_log_return':float(np.abs(e).mean()),'rmse_log_return':float(np.sqrt(np.mean(e**2))),'brier_up':float(((pup-aup)**2).mean())}

def scorecard(f):
    from btc_validation.runtime import validate_forecasts
    from btc_validation.core import IntegrityError,origin_hash,nonoverlap_indices,day,utc
    validate_forecasts(f,complete_grid=False)
    columns=['scope','horizon_days','model','n','directional_accuracy','mae_log_return','rmse_log_return','brier_up','origin_set_sha256','eligible_prospective_n']
    d=f[(f.status=='COMPLETE')&f.model.isin(['price_ridge','price_macro_ridge'])].copy()
    if d.empty:return pd.DataFrame(columns=columns)
    rows=[]
    for h,g in d.groupby('horizon_days'):
        a=g[g.model=='price_ridge'].sort_values('origin_date');b=g[g.model=='price_macro_ridge'].sort_values('origin_date')
        if a.origin_date.tolist()!=b.origin_date.tolist():raise IntegrityError('Different completed forecast-origin sets')
        if not np.allclose(a.actual_log_return.astype(float),b.actual_log_return.astype(float),rtol=0,atol=1e-12):raise IntegrityError('Mismatched paired actual outcomes')
        times=[day(x) for x in a.origin_date]
        for scope,indices in [('weekly_overlap',list(range(len(a)))),('nonoverlap',nonoverlap_indices(times,int(h)))]:
            selected=[times[i] for i in indices]
            eligible=sum(utc(a.iloc[i].capture_time_utc)<=times[i]+pd.Timedelta(days=1) and utc(b.iloc[i].capture_time_utc)<=times[i]+pd.Timedelta(days=1) for i in indices)
            for name,x in [('price_ridge',a),('price_macro_ridge',b)]:rows.append({'scope':scope,'horizon_days':int(h),'model':name,**stats(x.iloc[indices]),'origin_set_sha256':origin_hash(selected),'eligible_prospective_n':eligible})
    return pd.DataFrame(rows,columns=columns).sort_values(['scope','horizon_days','model'])

def get(s,scope,h,m):
    q=s[(s.scope==scope)&(s.horizon_days==h)&(s.model==m)];return None if q.empty else q.iloc[0].to_dict()

def _legacy_promotion(s,old):
    p7,m7=get(s,'weekly_overlap',7,'price_ridge'),get(s,'weekly_overlap',7,'price_macro_ridge');p30,m30=get(s,'nonoverlap',30,'price_ridge'),get(s,'nonoverlap',30,'price_macro_ridge');p90,m90=get(s,'nonoverlap',90,'price_ridge'),get(s,'nonoverlap',90,'price_macro_ridge')
    status='INSUFFICIENT_DATA';reason='Prospective evidence has not reached the minimum review sample.'
    if all(x for x in [p7,m7,p30,m30]) and int(m7['n'])>=13 and int(m30['n'])>=3:
        win=m7['mae_log_return']<p7['mae_log_return'] and m7['brier_up']<p7['brier_up'] and m30['mae_log_return']<p30['mae_log_return'] and m30['brier_up']<p30['brier_up'] and m7['directional_accuracy']>=p7['directional_accuracy']-.03 and m30['directional_accuracy']>=p30['directional_accuracy']-.03
        status='WATCH_POSITIVE' if win else 'NO_EDGE_YET';reason='Short/medium prospective gate passed.' if win else 'Minimum sample reached, but macro has not added consistent incremental edge.'
    if all(x for x in [p7,m7,p30,m30,p90,m90]) and int(m7['n'])>=26 and int(m30['n'])>=6 and int(m90['n'])>=3:
        pairs=[(p7,m7),(p30,m30),(p90,m90)];wins=sum(m['mae_log_return']<p['mae_log_return'] and m['brier_up']<p['brier_up'] for p,m in pairs);bad=any(m['mae_log_return']>p['mae_log_return']*1.10 for p,m in pairs);dok=all(m['directional_accuracy']>=p['directional_accuracy']-.05 for p,m in pairs)
        if wins>=2 and not bad and dok:status='PROMOTION_REVIEW';reason='Prospective macro edge cleared the pre-registered review gate. Manual review is required.'
    return {'status':status,'previous_status':old,'changed':status!=old,'updated_utc':datetime.now(timezone.utc).isoformat(),'reason':reason,'auto_promoted':False,'review_policy':'Never auto-promote. PROMOTION_REVIEW only opens a human review.'}

def promotion(s,old):
    from btc_validation.runtime import require_pair_proof
    require_pair_proof(s)
    if not s.empty and (s.eligible_prospective_n<s.n).any():return {'status':'INSUFFICIENT_DATA','previous_status':old,'changed':old!='INSUFFICIENT_DATA','updated_utc':datetime.now(timezone.utc).isoformat(),'reason':'Delayed-origin diagnostics cannot satisfy clean prospective review. Original forecasts remain immutable.','auto_promoted':False,'review_policy':'Separate issued-before-target-start evidence required; never auto-promote.'}
    return _legacy_promotion(s,old)
