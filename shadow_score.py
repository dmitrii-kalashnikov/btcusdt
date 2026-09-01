from __future__ import annotations
import math
from datetime import datetime,timezone
import numpy as np
import pandas as pd

def mature(f:pd.DataFrame,daily:pd.DataFrame)->pd.DataFrame:
    p=daily.copy(); p['date']=pd.to_datetime(p.time,utc=True).dt.strftime('%Y-%m-%d'); closes=dict(zip(p.date,p.close.astype(float)))
    for i,r in f.iterrows():
        if str(r.get('status'))=='COMPLETE': continue
        due=str(r.due_date)[:10]
        if due not in closes: continue
        actual=float(closes[due]); lr=math.log(actual/float(r.spot)); f.at[i,'actual_price']=actual; f.at[i,'actual_log_return']=lr; f.at[i,'actual_up']=float(lr>0); f.at[i,'status']='COMPLETE'
    return f

def stats(g):
    pred=pd.to_numeric(g.predicted_log_return); act=pd.to_numeric(g.actual_log_return); pup=pd.to_numeric(g.p_up); aup=pd.to_numeric(g.actual_up); e=pred-act
    return {'n':len(g),'directional_accuracy':float((np.sign(pred)==np.sign(act)).mean()),'mae_log_return':float(np.abs(e).mean()),'rmse_log_return':float(np.sqrt(np.mean(e**2))),'brier_up':float(((pup-aup)**2).mean())}

def scorecard(f):
    d=f[(f.status=='COMPLETE')&f.model.isin(['price_ridge','price_macro_ridge'])].copy(); rows=[]
    if d.empty: return pd.DataFrame(columns=['scope','horizon_days','model','n','directional_accuracy','mae_log_return','rmse_log_return','brier_up'])
    for (h,m),g in d.groupby(['horizon_days','model']): rows.append({'scope':'weekly_overlap','horizon_days':int(h),'model':m}|stats(g))
    for (h,m),g in d.sort_values('origin_date').groupby(['horizon_days','model']):
        chosen=[]; last=None
        for _,r in g.iterrows():
            t=pd.Timestamp(str(r.origin_date)[:10],tz='UTC')
            if last is None or (t-last).days>=int(h): chosen.append(r); last=t
        if chosen: rows.append({'scope':'nonoverlap','horizon_days':int(h),'model':m}|stats(pd.DataFrame(chosen)))
    return pd.DataFrame(rows).sort_values(['scope','horizon_days','model'])

def get(s,scope,h,m):
    q=s[(s.scope==scope)&(s.horizon_days==h)&(s.model==m)]; return None if q.empty else q.iloc[0].to_dict()

def promotion(s,old):
    p7,m7=get(s,'weekly_overlap',7,'price_ridge'),get(s,'weekly_overlap',7,'price_macro_ridge'); p30,m30=get(s,'nonoverlap',30,'price_ridge'),get(s,'nonoverlap',30,'price_macro_ridge'); p90,m90=get(s,'nonoverlap',90,'price_ridge'),get(s,'nonoverlap',90,'price_macro_ridge')
    status='INSUFFICIENT_DATA'; reason='Prospective evidence has not reached the minimum review sample.'
    if all(x for x in [p7,m7,p30,m30]) and int(m7['n'])>=13 and int(m30['n'])>=3:
        win=m7['mae_log_return']<p7['mae_log_return'] and m7['brier_up']<p7['brier_up'] and m30['mae_log_return']<p30['mae_log_return'] and m30['brier_up']<p30['brier_up'] and m7['directional_accuracy']>=p7['directional_accuracy']-.03 and m30['directional_accuracy']>=p30['directional_accuracy']-.03
        status='WATCH_POSITIVE' if win else 'NO_EDGE_YET'; reason='Short/medium prospective gate passed.' if win else 'Minimum sample reached, but macro has not added consistent incremental edge.'
    if all(x for x in [p7,m7,p30,m30,p90,m90]) and int(m7['n'])>=26 and int(m30['n'])>=6 and int(m90['n'])>=3:
        pairs=[(p7,m7),(p30,m30),(p90,m90)]; wins=sum(m['mae_log_return']<p['mae_log_return'] and m['brier_up']<p['brier_up'] for p,m in pairs); bad=any(m['mae_log_return']>p['mae_log_return']*1.10 for p,m in pairs); dok=all(m['directional_accuracy']>=p['directional_accuracy']-.05 for p,m in pairs)
        if wins>=2 and not bad and dok: status='PROMOTION_REVIEW'; reason='Prospective macro edge cleared the pre-registered review gate. Manual review is required.'
    return {'status':status,'previous_status':old,'changed':status!=old,'updated_utc':datetime.now(timezone.utc).isoformat(),'reason':reason,'auto_promoted':False,'review_policy':'Never auto-promote. PROMOTION_REVIEW only opens a human review.'}
