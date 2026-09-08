"""Production extension: observational context only; frozen forecasting untouched."""
from pathlib import Path
import json
import btc_release
import btc_wide_context

def record_review():
    path=Path('EXPERIMENT_LEDGER.md')
    entry=Path('research/WIDE_CONTEXT_LEDGER_ENTRY.md').read_text()
    marker='## wide-context-review-20260908'
    old=path.read_text()
    if marker not in old:
        tmp=path.with_suffix('.review.tmp')
        tmp.write_text(old+'\n'+entry+'\n',encoding='utf-8')
        tmp.replace(path)

def refresh_pending_publication():
    """One-time catchup of committed records; no new origin, model or anchor."""
    status_path=Path('shadow/issued_status.json')
    if not status_path.exists(): return None
    old=json.loads(status_path.read_text())
    if not any(x.get('status')=='AWAITING_PUBLICATION_PROOF' for x in old.get('row_status',[])):
        return None
    from btc_validation.issued import load_records, save_state
    from btc_validation.core import IntegrityError
    state=save_state(load_records())
    if state['evidence_failures'] or any(x['status']=='AWAITING_PUBLICATION_PROOF' for x in state['row_status']):
        raise IntegrityError('Committed issued forecast evidence is unavailable or late; no backdating allowed')
    return state

if __name__=='__main__':
    btc_release.install()
    btc_wide_context.install()
    record_review()
    refresh_pending_publication()
    btc_release.transport.main()
    btc_release.record_release()
