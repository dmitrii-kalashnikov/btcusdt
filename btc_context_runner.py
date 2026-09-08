"""Production extension: observational context only; frozen forecasting untouched."""
from pathlib import Path
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

if __name__=='__main__':
    btc_release.install()
    btc_wide_context.install()
    record_review()
    btc_release.transport.main()
    btc_release.record_release()
