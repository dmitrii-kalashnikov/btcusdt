# BTC Prospective Shadow Ledger

## btc-shadow-prospective-v1.2 — LIVE / PROSPECTIVE

Status: **LIVE / FAIL-CLOSED / NO AUTO-PROMOTION**

- Training cutoff: `2026-08-31`.
- 2024–2025 holdout: already consumed by the prior frozen experiments; never reopened or relabeled pristine.
- Frozen macro history: audited ALFRED PIT seed from `btc-macro-pit-v1.2`, SHA256 `df13f1cf959d598f0209a8b225e6650d0df3638d9c2ffb14cf45fc562aab793b`.
- Frozen comparison: `price_ridge` versus `price_macro_ridge`, Ridge `alpha=50`, 10 price features and 39 macro features.
- Primary reference forecast: frozen price/4Y-cycle equal-weight ensemble; the broad macro Ridge remains NOT_PROMOTED.
- Model promotion: impossible automatically. `PROMOTION_REVIEW` only opens manual review.

### Live source timing

For every new origin from `2026-09-07` onward:

1. Monday 16:30 `America/Merida` / 22:30 UTC: scheduled source capture reads the 14 official FRED series pages and freezes exactly one observation per series in `preclose_macro_snapshots.csv`.
2. The packet must be complete, unique, numeric, and have `capture_time_utc < target_btc_close_time_utc` where target close is Tuesday 00:00 UTC.
3. Tuesday 09:15 UTC / 03:15 `America/Merida`: GitHub `BTC Prospective Shadow` consumes the already-frozen packet plus official Binance Vision BTCUSDT daily data.
4. Tuesday 05:00 `America/Merida`: condition watch checks workflow health, source-packet integrity, packet/forecast origin parity, staleness and promotion gates; it stays silent when healthy.

The seeded origin `2026-08-31` predates source-contract v1.2 and is explicitly exempt from the Monday pre-close packet requirement.

### Source transport history

A direct GitHub-hosted-runner FRED/ALFRED transport was tested and repeatedly timed out against official St. Louis Fed endpoints. Before any post-2026-08-31 outcome matured, live source transport was separated from the model runtime: scheduled ChatGPT Web reads the same official FRED series pages before target BTC close and immediately persists the immutable packet to GitHub. This was a source-transport change only; model, features, alpha, scoring, gates and holdout governance were unchanged.

### Smoke proof

- GitHub Actions run `33470882712`: SUCCESS, end-to-end v1.2 smoke.
- GitHub Actions run `33471284547`: SUCCESS after adding BTC-source-lag fail-closed guard and runtime/contract push-smoke paths.
- Latest read-back after the final smoke: `origin_date=2026-08-31`, `btc_latest_close=78581.29`, `forecast_rows_total=15`, `completed_rows_total=0`, `promotion_status=INSUFFICIENT_DATA`, `auto_promoted=false`.
- No open BTC shadow/pre-close data-runtime issues remained at final read-back.

### Fail-closed rules

- A new origin cannot be created without exactly 14 valid pre-close macro rows for that origin.
- If a valid pre-close packet is newer than the latest BTC origin, the shadow run fails closed rather than silently using stale BTC data.
- Missing/partial/duplicate/late macro packet blocks the new macro forecast.
- No forecast is retroactively changed after its origin.
- No source/runtime failure can promote a model.

### Pre-registered edge gates

`WATCH_POSITIVE`: at least 13 completed weekly 7d forecasts and 3 non-overlapping 30d forecasts; macro must beat price-only on both MAE and Brier at both horizons with no material directional hit.

`PROMOTION_REVIEW`: at least 26 completed 7d, 6 non-overlapping 30d and 3 non-overlapping 90d forecasts; macro must win both MAE and Brier on at least 2 of 3 horizons, have no >10% MAE deterioration on any, and keep directional accuracy within 5 percentage points of price-only. This only opens manual review; it never changes the primary model automatically.
