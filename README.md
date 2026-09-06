# BTC Quant & Macro System

One repository, one BTC project, one user-facing report: the existing Google Sheet tab `BTC FINAL REPORT`.

The repository has three execution roles only:

1. **BTC Production Report** — current market/source collection and report publication.
2. **BTC Prospective Shadow** — frozen weekly prospective model evaluation; zero decision weight until reviewed promotion.
3. **BTC QA & Research** — tests on code changes; expensive historical research only when manually requested.

Old workflow generations and one-time handoff mechanisms do not belong in `main`. Git history is the archive. Current code uses canonical filenames rather than `v3/v4/v5/...` runner copies.

## Runtime flow

`btc_release.py` -> `btc_transport.py` / `btc_production.py` -> `live/report.csv` + `live/status.json` -> existing Google Sheet import.

Production and Shadow share the same concurrency group so they cannot write prospective state at the same time.

### Cadence

- **Production:** hourly at minute 23 UTC. This matches the roughly hourly Google import behavior and keeps the sheet inside its two-hour freshness guard without wasting runs every few minutes.
- **Prospective Shadow:** Tuesday 09:15 UTC, once per week. Long-horizon model evidence does not improve by refitting every hour.
- **Macro pre-close packet:** collected by the hourly Production job during the Monday 20:00–24:00 UTC capture window; the first valid complete packet is immutable.
- **QA:** only on relevant code/workflow/freeze changes or pull requests.
- **Full historical research/backtests:** manual only, or after a source/model contract change or when new prospective outcomes mature. Never on the hourly production schedule.

## Active code

### Production
- `btc_release.py` — release orchestration and source normalization.
- `btc_transport.py` — bounded external transport/source handling.
- `btc_production.py` — report construction and production contracts.

### Models / research
- `btc_baseline.py` + `run_baseline_fresh.py` — frozen baseline benchmark.
- `shadow_sources.py`, `shadow_model.py`, `shadow_score.py`, `shadow_run.py` — prospective shadow model.
- `macro_pit.py` + `macro_pit_runner.py` — canonical current macro point-in-time research runner.
- `leading_signal_backtest.py`, `derivatives_backtest.py` — manual diagnostics, not independent agents.

### Validation
- `btc_validation/` — integrity, collection, issuance and replay contracts.
- `test_*.py` and `btc_validation/test_*.py` — discovered automatically by the QA workflow.

### Frozen/current state
- `BASELINE_FREEZE_v2.json`
- `MACRO_FREEZE_v1_2.json`
- `shadow/SHADOW_FREEZE_v1_2.json`
- `btc_validation/*FREEZE*.json` / integrity evidence
- `shadow/forecasts.csv`, `shadow/preclose_macro_snapshots.csv`, `shadow/scorecard.csv`, `shadow/promotion_status.json`, `shadow/last_run.json`
- `live/report.csv`, `live/status.json`

## Governance

- Development data end: 2021-12-31.
- Validation: 2022-01-01 through 2023-12-31.
- 2024-2025 evidence has already been consumed and must never be relabeled pristine/unseen.
- Training rows must satisfy `s + horizon <= forecast_time`; features must be observable by forecast time.
- Missing data are not silently filled with stale values or zeros.
- No auto-trading and no automatic model promotion.
- User-facing probability claims are forbidden until a specific model/horizon has adequate calibration evidence.
- Production remains `ABSTAIN` / decision weight 0 until promotion governance explicitly changes.

## Workflows

Only these workflow files should exist:

- `.github/workflows/btc-production.yml`
- `.github/workflows/btc-shadow.yml`
- `.github/workflows/btc-integrity.yml`

If another workflow is introduced, it must replace or extend one of these roles unless there is a documented architectural reason for a new persistent execution role.
