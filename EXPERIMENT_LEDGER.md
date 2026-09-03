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

## btc-macro-pit-v1.2 — VALIDATION FAILED / NOT PROMOTED

Status: **COMPLETED / POINT-IN-TIME DATA PASS / MODEL PROMOTION FAIL**

- Frozen manifest canonical SHA256: `6af1b586910fd3b7dc7c9f858b3c412866507a8c7bf4f9c96193c61209a6d4b1`
- GitHub Actions run: `33467402243`
- Checked-out run commit: `1501b56dc24fd2978b27470fe8c6c0291e86debe`
- Result artifact ID: `9785410478`
- Result artifact ZIP SHA256: `adafdcc103a8d9f0082eaa90f6072495c3d8a9e4e9f60e864dcf09cac2ed3b39`
- BTC as-of: `2026-08-31`, close `$78,581.29`
- ALFRED weekly origins: `453`
- Point-in-time series used: `14`
- Macro features: `39`
- Hard invariant: `available_at <= forecast_time`
- Validation window: `2022-01-01` through `2023-12-31`
- 2024–2025 results are secondary only because that period had already been consumed by the earlier price/cycle benchmark.
- Source-only exclusions made before any macro-model metrics were observed: `BAMLH0A0HYM2` and `SP500`.

### Validation comparison — fixed Ridge alpha 50

| Horizon | Price-only MAE | Price+macro MAE | Macro MAE change | Price-only direction | Price+macro direction | Promotion |
|---:|---:|---:|---:|---:|---:|---|
| 7d | 0.055923 | 0.063529 | +13.60% worse | 48.08% | 49.04% | FAIL |
| 30d | 0.127868 | 0.161303 | +26.15% worse | 50.00% | 49.04% | FAIL |
| 90d | 0.291102 | 0.352876 | +21.22% worse | 54.81% | 55.77% | FAIL |
| 180d | 0.502666 | 0.641170 | +27.55% worse | 63.46% | 25.96% | FAIL |
| 365d | 0.543321 | 1.180845 | +117.34% worse | 77.88% | 28.85% | FAIL |

The price+macro Ridge is not promoted because its validation MAE and RMSE are worse at all five horizons and its Brier score is also worse at all five horizons. Small directional improvements at 7d and 90d do not offset the magnitude/probability degradation.

### Unpromoted macro scenario as of 2026-08-31

These numbers are retained for audit only and must **not** be presented as the primary forecast because the macro model failed validation.

| Horizon | Macro forecast price | Macro return | Macro baseline P(up) |
|---:|---:|---:|---:|
| 7d | $77,225.07 | -1.73% | 42.57% |
| 30d | $73,049.57 | -7.04% | 35.45% |
| 90d | $66,177.99 | -15.78% | 31.89% |
| 180d | $89,617.79 | +14.04% | 59.75% |
| 365d | $210,539.67 | +167.93% | 90.92% |

The 365d macro output is a clear extrapolation warning, consistent with the model's failed long-horizon validation. It is not an investable forecast.

### Source availability decisions

- `BAMLH0A0HYM2`: excluded because the live ALFRED history required for 2018+ could not be reconstructed under the current ICE/FRED retention window.
- `SP500`: excluded because the required historical-vintage requests returned HTTP 400 and FRED explicitly limits the S&P series to ten years of daily history. `NASDAQCOM` remains the equity-risk proxy and provided all 453 requested vintage snapshots.
- No revised/current-history substitution was allowed for either excluded series.

### Security and reproducibility

The FRED credential was passed to the successful run through a one-time RSA-OAEP handoff. The workflow destroyed the plaintext credential and ephemeral RSA private key after execution. Repository code, model artifacts, PIT data artifacts, and logs do not contain the plaintext credential.

## leading-signal-diagnostic-v1 — HISTORICAL ANALOG KNN REJECTED

Status: **COMPLETED / DIAGNOSTIC / NOT PROMOTED**

- GitHub Actions run: `33798370429`
- Commit: `a7119db2c5ef052d4a6ab84472186deb5f116ea4`
- Result artifact ID: `9910084336`
- Artifact ZIP SHA256: `00d4418c4f85c5ba654224bd58f5fc9ffcb84c6fef3b33c3181a33e0d686bca2`
- Data source: official Binance public market-data mirror `data-api.binance.vision`, BTCUSDT 1d.
- Model: fixed KNN historical analog, `k=15`, inverse-distance weighting, standardized frozen price/cycle feature set.
- No-leakage rule: at origin index `i` and horizon `h`, training ends at `i-h`, so every fitted forward-return label is fully realized before the forecast origin.
- This is diagnostic only: 2024–2025 is already consumed and 2026 YTD is not pristine prospective evidence for an architecture designed in September 2026.

### Validation 2022–2023 versus existing price-only baseline

| Horizon | KNN MAE | Price-only MAE | KNN change | KNN direction | Promotion |
|---:|---:|---:|---:|---:|---|
| 7d | 0.068434 | 0.055923 | +22.37% worse | 48.57% | FAIL |
| 30d | 0.225868 | 0.127868 | +76.64% worse | 35.24% | FAIL |
| 90d | 0.475915 | 0.291102 | +63.49% worse | 55.24% | FAIL |
| 180d | 0.786472 | 0.502666 | +56.46% worse | 63.81% | FAIL |
| 365d | 0.625045 | 0.543321 | +15.04% worse | 77.14% | FAIL |

The historical-nearest-neighbor concept does not add enough predictive value in this form. Directional accuracy at long horizons is partly a bull-regime/base-rate effect and does not compensate for materially worse magnitude error.

### Additional diagnostics

On already-consumed 2024–2025 the KNN directional accuracy was 55.24%, 47.62%, 48.57%, 39.05%, and 45.45% for 7/30/90/180/365d respectively, with MAE 0.058606, 0.170663, 0.382225, 0.599853, and 0.936283. It therefore failed to generalize even on the consumed secondary period.

2026 YTD diagnostic directional accuracy was 37.14% (7d), 45.16% (30d), 56.52% (90d), and 30.00% (180d); samples are small and this period is not a clean holdout. Non-overlapping samples become extremely small beyond 30d, so no long-horizon claim is accepted from this diagnostic.

Decision: **REJECT this KNN analog formulation. Do not use it in the user-facing forecast or ensemble.**

## Governance for next stage

1. Preserve all completed experiments and failures; do not rewrite outcomes.
2. Do not promote the broad 39-feature macro Ridge.
3. Do not promote `leading-signal-diagnostic-v1` KNN historical analog formulation.
4. Any new architecture may use development/validation evidence, but it cannot claim 2024–2025 as a pristine final holdout.
5. Freeze the next architecture before scoring it on later data; use post-2026-08-31 observations prospectively for clean evidence.
6. Keep the four-year-cycle signal as a regime/sign input rather than using its raw magnitude as a standalone price forecast.
7. Never store `FRED_API_KEY` or any other plaintext secret in repository contents, artifacts, cache manifests, or logs.
