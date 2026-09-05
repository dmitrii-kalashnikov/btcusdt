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

## btc-derivatives-pit-v1 — VALIDATION DEFECT / NOT PROMOTED

Status: **COMPLETED RUNTIME / FORMAL COMPARATOR INVALID / NOT PROMOTED**

- Model family: fixed Ridge `alpha=50`, price-only versus price + 11 derivatives features.
- Derivatives features: OI 1/7/30d changes; funding 1/7/30d means and 90d z-score; top-trader, global-account and taker-ratio 90d z-scores.
- Horizons attempted: `7/30/90d`.
- Data source: official Binance Vision USD-M `BTCUSDT` futures archives; data range in completed artifact `2022-01-01` through `2026-08-31`, `1704` daily rows.
- No-leakage implementation: expanding fit with training labels fully realized before the origin (`i-h` boundary); all model features backward-looking.
- GitHub Actions rerun after deterministic aggregation fix: run `33913421193`, commit `52eff3e76d525f73b5f4ab4524714e30af51dd31`, conclusion `success`.
- Result artifact ID: `9952310218`; artifact digest `sha256:6919dfddb15e929631c9578d1de3e10be60c4e705c3fb010f61c4b8381cea4ba`.
- Runtime fix only dropped a duplicate retained `time` column before `reset_index`; it did **not** alter model features, alpha, horizon, split, threshold, or source family.

### Formal output defect

The emitted validation `mae_change_pct` compares different forecast-origin sets because price-only and price+derivatives rows are independently dropped for feature availability. Validation sample counts are `65 vs 16` at 7d, `62 vs 12` at 30d, and `53 vs 4` at 90d. Those cross-model MAE deltas therefore are **not valid promotion evidence** and must not be interpreted as an OOS win/loss comparison.

### QA matched-origin diagnostic — same frozen models, diagnostic only

To diagnose the comparator defect without changing the frozen model/features/alpha/splits, both predictions were rescored only on origins available to **both** models. This changes the scoring sample and is therefore QA evidence, not a rewritten frozen result and not a new promotion test.

| Horizon | Common n | Price-only MAE | Price+derivatives MAE | Derivatives MAE change | Price direction | Derivatives direction | Independent n |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 7d | 16 | 0.049226 | 0.053668 | +9.02% worse | 25.00% | 43.75% | 16 |
| 30d | 12 | 0.128519 | 0.237179 | +84.55% worse | 50.00% | 16.67% | 3 |
| 90d | 4 | 0.407084 | 0.637239 | +56.54% worse | 100.00% | 0.00% | 1 |

Matched-origin validation is adverse on MAE at all three horizons and independent long-horizon samples are inadequate. This closes any promotion interpretation for this version.

### Secondary evidence — not pristine

On the already-consumed 2024–2025 diagnostic block, price+derivatives MAE was worse than price-only by `+5.72%`, `+18.29%`, and `+12.66%` for 7/30/90d respectively. On 2026 YTD, which is not pristine prospective evidence for a model designed in September 2026, derivatives were also worse on the weekly-origin MAE comparison by `+1.68%`, `+4.35%`, and `+42.34%`.

A fixed descriptive crowding event study (30d price and OI rising, positive funding crowding, top-trader crowding, weak taker flow) did not establish a robust bearish rule: signal mean returns were positive at 7d/30d/90d; the 90d median was mildly negative but the down-rate was only `52.34%`. It receives zero decision weight.

Decision: **NOT PROMOTED.** Current live OI/funding/L/S/taker/basis data remain descriptive EXPERIMENTAL inputs only. Any corrected comparative design must be preregistered as a separate experiment and earn later pristine prospective evidence; 2024–2025 cannot be reopened or relabeled pristine.

## Governance for next stage

1. Preserve all completed experiments and failures; do not rewrite outcomes.
2. Do not promote the broad 39-feature macro Ridge.
3. Do not promote `leading-signal-diagnostic-v1` KNN historical analog formulation.
4. Do not promote `btc-derivatives-pit-v1`; its formal comparator has unequal origin sets and the matched-origin QA check is adverse.
5. Any new architecture may use development/validation evidence, but it cannot claim 2024–2025 as a pristine final holdout.
6. Freeze the next architecture before scoring it on later data; use post-2026-08-31 observations prospectively for clean evidence.
7. Keep the four-year-cycle signal as a regime/sign input rather than using its raw magnitude as a standalone price forecast.
8. Never store `FRED_API_KEY` or any other plaintext secret in repository contents, artifacts, cache manifests, or logs.

## release-integrity-20260905 — LOCAL REPLAY / NO MODEL PROMOTION

User-authorized release candidate. Original freezes, seed and old forecast rows remain unchanged. This records completed LOCAL evidence, not a deployment or predictive-performance guarantee.

- Local suite: 128 passed, Python 3.13.5 / NumPy 2.3.5 / pandas 2.2.3 / scikit-learn 1.8.0. Deployment uses existing pinned Python 3.12 dependencies and performs its own release smoke test.
- Replayed 3,302 BTC daily rows (2017-08-17..2026-08-31), the 14-series PIT seed, and separately reconstructed 2,191 calendar days of corrected derivatives (2020-09-01..2026-08-31). No online download or random split in local replay.
- Paired return/risk/derivative metrics match archived pinned-environment CI to maximum absolute numeric difference 2.45e-15. Regression assertions, calendar checks, source-byte hashes and retained real-source parsing passed.
- Baseline comparison covers all 7/30/90/180/365-day horizons. Compact macro/risk and derivative-family ablations remain the preregistered 7/30-day experiments; NOT expanded post hoc to hunt winners.
- Compact macro return MAE remains +2.01% / +4.49% worse at 7d/30d on selection-safe validation; n=103/100.
- OI/funding validation MAE +3.55% / +0.55% worse, n=101/98 (30d non-overlap n=20).
- Positioning validation MAE +6.61% / +10.02% worse, n=57/54 (30d non-overlap n=11).
- Taker validation MAE +2.35% worse at 7d and -1.25% better at 30d, n=103/100. The small 30d improvement did not retain an edge on consumed 2024-2025 (+0.41% worse); no promotion.
- Risk: 7d macro Brier improved 0.2145 to 0.2026 on validation but worsened 0.2438 to 0.2502 on consumed 2024-2025. Probabilities remain uncalibrated and hidden.
- Full historic CI 33934720401 and live-source candidate CI 33936092468 completed successfully before this local release audit. Earlier UTC-boundary, duplicate-archive, Reader formatting and source-health failures are retained in Actions; no failed outcomes deleted.
- First local normalized-funding replay loader failed on mixed fractional-second ISO strings; the TEST LOADER was corrected to format=ISO8601 and replay passed. No dataset values, horizon, model or threshold changed.
- All 2024-2025 results remain CONSUMED SECONDARY DIAGNOSTICS. Original archive PIT provenance is not claimed solely from retrospective checksums. Non-overlapping outcomes are not automatically independent. Bootstrap intervals remain diagnostic, not multiple-test-adjusted promotion evidence.
- Runtime changes: no heavy history on code pushes; one PR regression suite; historical QA only explicit workflow_dispatch/local execution; hourly main report and weekly prospective scorer use a shared non-cancelling queue. Monday capture fallback starts only after original 22:30 UTC capture time.
- Public report conditional paths and recent macro changes are EXPERIMENTAL, decision weight zero. No algorithms promoted, no trades, no paid provider.

