# BTC Forecast Lab — price/cycle baseline

Leakage-safe Bitcoin forecasting benchmark used before macro/on-chain factors are admitted.

## Frozen experiment

`BASELINE_FREEZE_v2.json` fixes the rules before holdout scoring:

- Development: through 2021-12-31
- Validation: 2022-01-01 through 2023-12-31
- Locked holdout: 2024-01-01 through 2025-12-31
- Forecast-origin stride: 7 days
- Horizons: 7 / 30 / 90 / 180 / 365 days
- Models: expanding constant mean, momentum, 4-calendar-year cycle analog, fixed-alpha price Ridge, fixed equal-weight ensemble
- Hard leakage rule: for origin `t` and horizon `h`, every fitted training row `s` must satisfy `s + h <= t`
- Holdout is never used to tune features, coefficients, alpha, cycle definition, or ensemble weights.

Freeze SHA256: `2cef61955f200a63bb3341a39590275e3d8eae0dd79824fba901e0e8ee341fb1`

## Market data

The workflow downloads official Binance Vision BTCUSDT spot daily archives. Archive SHA256 companions are checked whenever Binance publishes them. The script validates continuous 24/7 daily coverage and OHLC invariants before forecasting.

## Outputs

The GitHub Actions artifact `btc-baseline-results` contains:

- `btc_daily.csv`
- `data_manifest.json`
- `predictions.csv`
- `benchmark_metrics.csv`
- `benchmark_metrics_nonoverlap.csv`
- `prospective_forecast.csv`
- `run_summary.json`

## FRED / ALFRED

No FRED key is stored in this repository. Macro point-in-time ingestion remains a separate stage. The price/cycle benchmark must be beaten on the locked holdout before macro factors are promoted.
