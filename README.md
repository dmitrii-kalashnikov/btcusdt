# BTC production monitor and forecast lab

Read-only market monitoring plus frozen experimental forecasting. No orders,
paid market-data subscription, auto-promotion or claim of a profitable strategy.
The one user-facing destination is the existing `BTC FINAL REPORT` Google tab.
Internal GitHub artifacts are execution evidence, not additional user reports.

## Production chain

`BTC Production Report` runs hourly at minute 23 UTC. It validates the frozen
contract and regression suite, collects public sources, writes `live/report.csv`
and `live/status.json`, verifies their hash and schema, and publishes to main.
A shared writer lock serializes it with the weekly shadow workflow. On main,
the report runner refreshes origin/main before collecting to avoid stale state.
No report-only commit re-triggers itself.

The existing Google tab imports that single CSV using IMPORTDATA. Google has its
own approximately hourly refresh, independent of GitHub scheduling. An expiry
serial in the CSV supports a formula-based two-hour freshness warning; neither
GitHub cron nor Google import is a real-time SLA. Manual writers must not replace
the managed import range.

Critical sources are live BTCUSDT spot, closed-candle price/flow data, the frozen
forecast file, ETF flows and all 14 required FRED series. A critical failure is
published explicitly and makes the workflow fail; it is never filled with stale
values or zeros. Optional source absence is PARTIAL, not an all-sources PASS.
Runtime failure issues are deduplicated.

## Source semantics

- Spot: official public Binance market-data API, BTCUSDT, denominated in USDT.
- Macro: exact observation rows from public FRED series pages through basic
  anonymous Jina Reader, without a purchased key. The response hash identifies
  Reader output, not the original HTML. Missing/ambiguous data fail validation.
  DFF uses full Markdown without readability filtering to retain its data table.
  H.10 dollar-index observations are released weekly for the preceding week;
  the report shows observation dates rather than pretending they are live.
- ETF: public Farside fund table; partial rows and missing cells are not zero.
  Three/five/twenty-session sums require complete consecutive source rows.
- OI/futures flow: checksum-verified unrestricted Binance Vision daily archives;
  explicitly delayed, not rolling live observations or a substitute exchange.
- Live futures funding: unavailable on this host after HTTP 451. The restriction
  is respected; no proxy workaround, invented rate or silent venue substitution.
- True liquidation maps, on-chain flows and Coinbase premium are not connected.

Basic Reader is a free external dependency, not a guaranteed-availability service.
Official interface references: https://jina.ai/reader/ and
https://github.com/jina-ai/reader . H.10 publication schedule:
https://www.federalreserve.gov/releases/h10/ .

## Prospective forecasts

The weekly shadow schedule remains Tuesday 09:15 UTC. In the Monday 20:00–24:00
UTC capture window, the report collector can append one complete 14-series
macro packet before BTC daily close. Existing packets are immutable. A missing
packet blocks a new forecast; it is not recreated retrospectively.

Frozen historical forecasts retain their original origin prices and dates.
Uncalibrated p_up is not exposed as an actionable probability. New issued-shadow
records use a future target anchor after issuance and require first-publication
proof before being counted. No automatic promotion is enabled. The report's
ABSTAIN / zero decision weight is deliberate until a reviewed successor has
credible prospective evidence. Volatility scales are descriptive scenarios,
not calibrated confidence intervals or target prices.

## Research and actual QA evidence

Development: through 2021-12-31. Validation: 2022–2023. The originally locked
2024–2025 holdout has ALREADY BEEN CONSUMED and is now secondary diagnostics;
re-running it does not make it unseen. Features, alpha, calendar cycle definition
and frozen ensemble weights must not be tuned on that period.

The historical training rule is s + h <= t; missing calendar days are never
compressed into shorter horizons. Only exact raw-string duplicate archive rows
may collapse. Conflicting timestamps, including different high-precision numeric
strings, are rejected. Missing funding stays missing, not zero.

Full historical integrity run 33934720401 completed successfully on commit
745ca3d0d1f7488e08e3d9ea5ce236a08bdf5cd2: 74 integrity tests, corrected official
archive collection and all three derivative-family diagnostics. Zero source or
schema failures; 72,663 exact duplicate records removed with a source audit.
Artifact 9959819883 SHA256:
4538e2536198f670d3fe6222c51843b1ca54cf97ea67c90e7302faf15239406e.
This is evidence of execution/integrity, not evidence of predictive edge.

Frozen BASELINE_FREEZE_v2.json byte SHA256:
3215500ea699861773bcb72fceff4d170b3c1cd0b276c60ec7a9c91b958ddc1f.
Old predictions and the frozen model files remain unchanged.
