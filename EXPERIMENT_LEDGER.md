# Experiment Ledger

## btc-price-cycle-baseline-v2 — CONSUMED HOLDOUT

Status: **COMPLETED / HOLDOUT CONSUMED — DO NOT TUNE AGAINST 2024–2025**

- Frozen manifest canonical SHA256: `2cef61955f200a63bb3341a39590275e3d8eae0dd79824fba901e0e8ee341fb1`
- Git commit used for fresh run: `5ba35800f7bbc06e8c0bb7788a513eea010cb53c`
- GitHub Actions run: `33464964317`
- Result artifact ID: `9784547743`
- Result artifact ZIP SHA256: `c38e526033f1ab76139423174a98a5b3afdf293925b760b5746ec20a8a5ddbb8`
- Market-data CSV SHA256: `095928e70c31b5991f5f46fa12a6bd1fb0c331bf8a93174f0baf90e8a7de761e`
- Data source: official Binance Vision spot `BTCUSDT`, interval `1d`
- Data range used: `2017-08-17` through `2026-08-31` UTC
- Rows: `3302`
- Locked holdout: `2024-01-01` through `2025-12-31`
- Holdout was not used to fit/tune this frozen benchmark.
- After this run was inspected, the 2024–2025 holdout became **consumed**. New model choices motivated by these results must not claim 2024–2025 as a pristine final holdout.

### Holdout headline metrics

| Horizon | Best MAE model | MAE log-return | Directional accuracy | 4Y cycle directional accuracy | 4Y cycle MAE |
|---:|---|---:|---:|---:|---:|
| 7d | constant mean | 0.052248 | 50.48% | 50.48% | 0.093883 |
| 30d | constant mean | 0.105911 | 56.19% | 46.67% | 0.229833 |
| 90d | momentum | 0.206697 | 35.24% | 44.76% | 0.404458 |
| 180d | equal-weight ensemble | 0.229995 | 66.67% | 69.52% | 0.496690 |
| 365d | equal-weight ensemble | 0.273060 | 82.76% | 89.66% | 0.695709 |

For 365d, the raw four-year analog had strong sign classification (`89.66%`) and Brier score (`0.103303`) but very poor magnitude calibration (`MAE=0.695709` versus ensemble `0.273060`). This is an observation from the consumed holdout, **not permission to retune and rescore on the same holdout**.

### Non-overlap robustness warning

Forecast origins in the headline table are weekly and therefore overlap for horizons above 7 days. A non-overlapping robustness table is included in the artifact. Its long-horizon sample sizes are small (30d `n=21`, 90d `n=9`, 180d `n=5`, 365d `n=2`), so long-horizon conclusions must be treated as preliminary rather than statistically established.

### Prospective price-only/cycle baseline as of 2026-08-31

Spot close: `$78,581.29`.

Equal-weight frozen ensemble:

| Horizon | Forecast date | Forecast price | Forecast return | Baseline P(up) |
|---:|---|---:|---:|---:|
| 7d | 2026-09-07 | $78,196.64 | -0.49% | 47.92% |
| 30d | 2026-09-30 | $80,490.45 | +2.43% | 54.61% |
| 90d | 2026-11-29 | $80,956.41 | +3.02% | 53.03% |
| 180d | 2027-02-27 | $92,100.43 | +17.20% | 61.69% |
| 365d | 2027-08-31 | $102,591.93 | +30.56% | 63.99% |

`P(up)` is a simple baseline normal-approximation probability, not a fully calibrated posterior probability.

## Governance for next stage

1. Preserve this benchmark exactly; do not rewrite its artifact or metrics.
2. Macro/ALFRED architecture must be specified independently of 2024–2025 outcomes.
3. Use development/validation data for model design and hyperparameters.
4. Treat 2026+ forecasts as prospective/shadow evidence for any improvements motivated after opening the 2024–2025 holdout.
5. Never store `FRED_API_KEY` or any other secret in repository contents, artifacts, cache manifests, or logs.
