# BTC Prospective Shadow

Purpose: accumulate **truly prospective** evidence after the 2026-08-31 freeze without reusing the consumed 2024-2025 holdout as if it were unseen.

- Forecast run: weekly, Tuesday 09:15 UTC.
- BTC: official Binance Vision `BTCUSDT` daily archives, with official daily-ZIP tail fallback when the newest monthly archive is not yet published.
- Historical macro state: audited ALFRED point-in-time seed from `btc-macro-pit-v1.2`.
- New macro state: 14 official FRED series pages are read Monday at 16:30 `America/Merida` / 22:30 UTC, **before** the Monday BTC candle closes at Tuesday 00:00 UTC. The extracted packet is immediately written to `preclose_macro_snapshots.csv` and is immutable for that forecast origin.
- Source transport: scheduled ChatGPT Web + GitHub write, because repeated tests showed GitHub-hosted runners timing out against FRED/ALFRED while the official FRED pages remain reachable through Web. This transport change was made before any post-2026-08-31 outcome matured.
- Frozen comparison: `price_ridge` vs `price_macro_ridge`, Ridge alpha 50, training cutoff 2026-08-31.
- Primary reference: the existing price/4Y-cycle equal-weight ensemble is logged but does not change the incremental macro edge test.
- No auto-promotion. The strongest possible automated state is `PROMOTION_REVIEW`.

## Pre-registered gates

`WATCH_POSITIVE` requires at least 13 completed weekly 7-day forecasts and 3 non-overlapping 30-day forecasts, with macro beating price-only on both MAE and Brier at both horizons and no material direction hit.

`PROMOTION_REVIEW` requires at least 26 completed 7-day forecasts, 6 non-overlapping 30-day forecasts and 3 non-overlapping 90-day forecasts. Macro must win both MAE and Brier on at least 2 of the 3 horizons, have no >10% MAE deterioration on any of them, and keep direction accuracy within 5 percentage points of price-only.

These gates only trigger a review. They never alter the primary model automatically.

## Fail-closed source contract

For every new origin, `preclose_macro_snapshots.csv` must contain exactly one row for each of the 14 frozen FRED series. Every row must have `capture_time_utc < target_btc_close_time_utc`. Missing, duplicate or ambiguous data blocks the new macro forecast; the system does not silently forward-fill a missing source packet.

`source_sha256` is the SHA256 of the canonical extracted observation string `series_id|observation_date|decimal value|source_url`. It fingerprints the official observation used; it is not represented as a hash of the whole FRED HTML page.

## Files

- `SHADOW_FREEZE_v1_2.json` — current frozen source/model/governance contract.
- `forecasts.csv` — immutable-origin prospective forecasts plus eventual realized outcomes.
- `preclose_macro_snapshots.csv` — official FRED observations captured before each target BTC close.
- `scorecard.csv` — overlapping weekly and non-overlapping robustness metrics.
- `promotion_status.json` — current gate state.
- `last_run.json` — latest source/integrity read-back.
- `seed_macro_weekly_features.csv` — frozen PIT history bootstrapped once from the audited v1.2 macro artifact and SHA-verified.
