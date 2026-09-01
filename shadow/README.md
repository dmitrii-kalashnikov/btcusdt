# BTC Prospective Shadow

Purpose: accumulate **truly prospective** evidence after the 2026-08-31 freeze without reusing the consumed 2024-2025 holdout as if it were unseen.

- Schedule: weekly, Tuesday 09:15 UTC.
- BTC: official Binance Vision `BTCUSDT` daily archives.
- Macro: key-free ALFRED `alfredgraph.csv` with the exact Monday `vintage_date`.
- Frozen comparison: `price_ridge` vs `price_macro_ridge`, Ridge alpha 50, training cutoff 2026-08-31.
- Primary reference: the existing price/4Y-cycle equal-weight ensemble is logged but does not change the incremental macro edge test.
- No auto-promotion. The strongest possible automated state is `PROMOTION_REVIEW`.

## Pre-registered gates

`WATCH_POSITIVE` requires at least 13 completed weekly 7-day forecasts and 3 non-overlapping 30-day forecasts, with macro beating price-only on both MAE and Brier at both horizons and no material direction hit.

`PROMOTION_REVIEW` requires at least 26 completed 7-day forecasts, 6 non-overlapping 30-day forecasts and 3 non-overlapping 90-day forecasts. Macro must win both MAE and Brier on at least 2 of the 3 horizons, have no >10% MAE deterioration on any of them, and keep direction accuracy within 5 percentage points of price-only.

These gates only trigger a review. They never alter the primary model automatically.

## Files

- `forecasts.csv` — immutable-origin prospective forecasts plus eventual realized outcomes.
- `macro_snapshots.csv` — exact-vintage source observations captured for each new origin.
- `scorecard.csv` — overlapping weekly and non-overlapping robustness metrics.
- `promotion_status.json` — current gate state.
- `last_run.json` — latest source/integrity read-back.
- `seed_macro_weekly_features.csv` — frozen PIT history bootstrapped once from the audited v1.2 artifact, then committed with SHA verification.
