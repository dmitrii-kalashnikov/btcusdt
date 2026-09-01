from __future__ import annotations

import hashlib
import io
import json
import math
import os
import statistics
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

SYMBOL = "BTCUSDT"
INTERVAL = "1d"
VISION = "https://data.binance.vision/data/spot"
START = date(2017, 8, 17)
HORIZONS = (7, 30, 90, 180, 365)
EVAL_STRIDE_DAYS = 7
FEATURES = (
    "ret_7d",
    "ret_30d",
    "ret_90d",
    "ret_180d",
    "ret_365d",
    "rv_30d",
    "rv_90d",
    "dist_ma_50",
    "dist_ma_200",
    "drawdown_from_ath",
)
FREEZE_SHA = "2cef61955f200a63bb3341a39590275e3d8eae0dd79824fba901e0e8ee341fb1"
OUT = Path("artifacts")
OUT.mkdir(exist_ok=True)

COLS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore",
]


def _month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fetch_zip(url: str, session: requests.Session) -> bytes | None:
    r = session.get(url, timeout=45)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    raw = r.content

    checksum = session.get(url + ".CHECKSUM", timeout=30)
    if checksum.status_code == 200:
        expected = checksum.text.strip().split()[0].lower()
        actual = _sha256(raw)
        if actual != expected:
            raise RuntimeError(f"SHA256 mismatch for {url}: {actual} != {expected}")
    elif checksum.status_code not in (403, 404):
        checksum.raise_for_status()
    return raw


def _parse_zip(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise RuntimeError(f"Expected one CSV in archive, got {names}")
        with zf.open(names[0]) as fh:
            df = pd.read_csv(fh, header=None, names=COLS)
    return df


def download_binance_daily() -> pd.DataFrame:
    now = datetime.now(timezone.utc).date()
    last_complete_day = now - timedelta(days=1)
    first_this_month = now.replace(day=1)
    last_complete_month_day = first_this_month - timedelta(days=1)

    session = requests.Session()
    session.headers.update({"User-Agent": "btc-forecast-lab/0.3"})
    parts: list[pd.DataFrame] = []
    source_archives: list[dict] = []

    # Completed months: compact official Binance Vision archives.
    if last_complete_month_day >= START:
        for y, m in _month_iter(START, last_complete_month_day):
            url = f"{VISION}/monthly/klines/{SYMBOL}/{INTERVAL}/{SYMBOL}-{INTERVAL}-{y:04d}-{m:02d}.zip"
            raw = _fetch_zip(url, session)
            if raw is None:
                continue
            parts.append(_parse_zip(raw))
            source_archives.append({"url": url, "sha256": _sha256(raw), "bytes": len(raw)})

    # Current month: daily archives are available the next day.
    d = first_this_month
    while d <= last_complete_day:
        url = f"{VISION}/daily/klines/{SYMBOL}/{INTERVAL}/{SYMBOL}-{INTERVAL}-{d.isoformat()}.zip"
        raw = _fetch_zip(url, session)
        if raw is not None:
            parts.append(_parse_zip(raw))
            source_archives.append({"url": url, "sha256": _sha256(raw), "bytes": len(raw)})
        d += timedelta(days=1)

    if not parts:
        raise RuntimeError("No Binance Vision archives were downloaded")

    raw = pd.concat(parts, ignore_index=True)
    raw["open_time"] = pd.to_numeric(raw["open_time"], errors="raise")
    # Binance spot archives switched from milliseconds to microseconds in 2025.
    raw["time"] = raw["open_time"].map(
        lambda x: pd.to_datetime(int(x), unit="us" if int(x) > 10**14 else "ms", utc=True)
    )
    for c in ("open", "high", "low", "close", "volume"):
        raw[c] = pd.to_numeric(raw[c], errors="raise")

    raw = raw.sort_values("time").drop_duplicates("time", keep="last")
    raw = raw[raw["time"].dt.date >= START].reset_index(drop=True)

    if (raw[["open", "high", "low", "close"]] <= 0).any().any():
        raise RuntimeError("Non-positive OHLC value")
    if (raw["high"] < raw[["open", "close"]].max(axis=1)).any():
        raise RuntimeError("High below open/close")
    if (raw["low"] > raw[["open", "close"]].min(axis=1)).any():
        raise RuntimeError("Low above open/close")
    if (raw["volume"] < 0).any():
        raise RuntimeError("Negative volume")

    gaps = raw["time"].diff().dropna()
    if not (gaps == pd.Timedelta(days=1)).all():
        bad = raw.loc[gaps[gaps != pd.Timedelta(days=1)].index, ["time"]]
        raise RuntimeError(f"BTC daily series has gaps: {bad.head().to_dict('records')}")

    daily = raw[["time", "open", "high", "low", "close", "volume"]].copy()
    daily.to_csv(OUT / "btc_daily.csv", index=False)
    csv_bytes = (OUT / "btc_daily.csv").read_bytes()
    manifest = {
        "source": "Binance Vision spot archive",
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "rows": int(len(daily)),
        "start": daily["time"].iloc[0].isoformat(),
        "end": daily["time"].iloc[-1].isoformat(),
        "csv_sha256": _sha256(csv_bytes),
        "archives": source_archives,
    }
    (OUT / "data_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return daily


def add_features_targets(df: pd.DataFrame) -> pd.DataFrame:
    out = df.sort_values("time").reset_index(drop=True).copy()
    px = out["close"].astype(float)
    logp = np.log(px)

    for h in HORIZONS:
        out[f"ret_{h}d"] = logp.diff(h)
        out[f"fwd_ret_{h}d"] = logp.shift(-h) - logp

    daily_ret = logp.diff()
    out["rv_30d"] = daily_ret.rolling(30, min_periods=30).std() * math.sqrt(365)
    out["rv_90d"] = daily_ret.rolling(90, min_periods=90).std() * math.sqrt(365)
    out["dist_ma_50"] = px / px.rolling(50, min_periods=50).mean() - 1.0
    out["dist_ma_200"] = px / px.rolling(200, min_periods=200).mean() - 1.0
    out["drawdown_from_ath"] = px / px.cummax() - 1.0
    return out


def _ridge() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("ridge", Ridge(alpha=10.0)),
    ])


def _p_up(mu: float, sigma: float) -> float:
    if not np.isfinite(mu):
        return float("nan")
    if not np.isfinite(sigma) or sigma <= 1e-12:
        return 0.5
    z = mu / sigma
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _predict_one(df: pd.DataFrame, i: int, h: int) -> dict[str, float]:
    target_col = f"fwd_ret_{h}d"
    current_time = df.at[i, "time"]

    # Label-availability gate: a training row s is allowed only if s+h <= forecast origin.
    train_end_i = i - h
    if train_end_i < 365:
        raise RuntimeError(f"Insufficient history at {current_time} for {h}d")
    train = df.iloc[: train_end_i + 1].dropna(subset=[target_col]).copy()
    y = train[target_col].astype(float)
    sigma = float(y.std(ddof=1))

    constant = float(y.mean())

    mom_col = f"ret_{h}d"
    valid = train[[mom_col, target_col]].dropna()
    x = valid[mom_col].to_numpy(float)
    yy = valid[target_col].to_numpy(float)
    denom = float(np.dot(x, x))
    beta = float(np.dot(x, yy) / denom) if denom > 1e-12 else 0.0
    x_now = float(df.at[i, mom_col]) if pd.notna(df.at[i, mom_col]) else 0.0
    momentum = beta * x_now

    analog_time = current_time - pd.DateOffset(years=4)
    analog_match = df.index[df["time"] == analog_time]
    if len(analog_match):
        analog_val = df.at[int(analog_match[0]), target_col]
        cycle = float(analog_val) if pd.notna(analog_val) else constant
    else:
        cycle = constant

    ridge_train = train.dropna(subset=[target_col])
    model = _ridge()
    model.fit(ridge_train[list(FEATURES)], ridge_train[target_col])
    ridge_pred = float(model.predict(df.loc[[i], list(FEATURES)])[0])

    ensemble = float(np.mean([constant, momentum, cycle, ridge_pred]))
    preds = {
        "constant_mean": constant,
        "momentum": momentum,
        "four_year_cycle": cycle,
        "ridge_price": ridge_pred,
        "equal_weight_ensemble": ensemble,
    }
    return {k: float(v) for k, v in preds.items()} | {"target_sigma": sigma}


def _origin_indices(df: pd.DataFrame, start: str, end: str) -> list[int]:
    s = pd.Timestamp(start, tz="UTC")
    e = pd.Timestamp(end + " 23:59:59", tz="UTC")
    mask = (df["time"] >= s) & (df["time"] <= e)
    idx = df.index[mask].tolist()
    if not idx:
        return []
    first_time = df.at[idx[0], "time"]
    return [i for i in idx if (df.at[i, "time"] - first_time).days % EVAL_STRIDE_DAYS == 0]


def generate_predictions(df: pd.DataFrame, split: str, start: str, end: str) -> pd.DataFrame:
    rows: list[dict] = []
    for i in _origin_indices(df, start, end):
        t = df.at[i, "time"]
        p0 = float(df.at[i, "close"])
        for h in HORIZONS:
            target_col = f"fwd_ret_{h}d"
            target = df.at[i, target_col]
            if pd.isna(target):
                continue
            pred = _predict_one(df, i, h)
            sigma = pred.pop("target_sigma")
            actual = float(target)
            for model_name, mu in pred.items():
                rows.append({
                    "split": split,
                    "time": t,
                    "horizon_days": h,
                    "model": model_name,
                    "prediction_log_return": mu,
                    "actual_log_return": actual,
                    "p_up": _p_up(mu, sigma),
                    "actual_up": float(actual > 0),
                    "spot": p0,
                    "forecast_price": p0 * math.exp(mu),
                    "actual_future_price": p0 * math.exp(actual),
                })
    return pd.DataFrame(rows)


def score(pred: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (split, h, model), g in pred.groupby(["split", "horizon_days", "model"]):
        err = g["prediction_log_return"] - g["actual_log_return"]
        rel_price_err = g["forecast_price"] / g["actual_future_price"] - 1.0
        brier = ((g["p_up"] - g["actual_up"]) ** 2).mean()
        rows.append({
            "split": split,
            "horizon_days": int(h),
            "model": model,
            "n": int(len(g)),
            "directional_accuracy": float((np.sign(g["prediction_log_return"]) == np.sign(g["actual_log_return"])).mean()),
            "mae_log_return": float(np.abs(err).mean()),
            "rmse_log_return": float(np.sqrt(np.mean(err ** 2))),
            "median_abs_log_error": float(np.median(np.abs(err))),
            "median_abs_price_pct_error": float(np.median(np.abs(rel_price_err))),
            "brier_up": float(brier),
            "mean_actual_return_pct": float((np.exp(g["actual_log_return"]) - 1.0).mean()),
            "mean_predicted_return_pct": float((np.exp(g["prediction_log_return"]) - 1.0).mean()),
        })
    return pd.DataFrame(rows).sort_values(["split", "horizon_days", "mae_log_return", "rmse_log_return"])


def score_nonoverlap(pred: pd.DataFrame) -> pd.DataFrame:
    chosen = []
    for (split, h, model), g in pred.sort_values("time").groupby(["split", "horizon_days", "model"]):
        last = None
        for _, row in g.iterrows():
            if last is None or (row["time"] - last).days >= int(h):
                chosen.append(row)
                last = row["time"]
    if not chosen:
        return pd.DataFrame()
    return score(pd.DataFrame(chosen)).rename(columns={"split": "split"})


def prospective(df: pd.DataFrame) -> pd.DataFrame:
    i = int(df.index[-1])
    t = df.at[i, "time"]
    spot = float(df.at[i, "close"])
    rows = []
    for h in HORIZONS:
        pred = _predict_one(df, i, h)
        sigma = pred.pop("target_sigma")
        for model_name, mu in pred.items():
            rows.append({
                "as_of": t,
                "forecast_date": t + pd.Timedelta(days=h),
                "horizon_days": h,
                "model": model_name,
                "spot": spot,
                "predicted_log_return": mu,
                "predicted_return_pct": math.exp(mu) - 1.0,
                "forecast_price": spot * math.exp(mu),
                "p_up": _p_up(mu, sigma),
            })
    return pd.DataFrame(rows)


def main() -> None:
    freeze = json.loads(Path("BASELINE_FREEZE_v2.json").read_text())
    if freeze.get("sha256") != FREEZE_SHA:
        raise RuntimeError("Baseline freeze SHA mismatch")

    daily = download_binance_daily()
    frame = add_features_targets(daily)

    validation = generate_predictions(frame, "validation", "2022-01-01", "2023-12-31")
    holdout = generate_predictions(frame, "holdout", "2024-01-01", "2025-12-31")
    predictions = pd.concat([validation, holdout], ignore_index=True)
    metrics = score(predictions)
    nonoverlap = score_nonoverlap(predictions)
    live = prospective(frame)

    predictions.to_csv(OUT / "predictions.csv", index=False)
    metrics.to_csv(OUT / "benchmark_metrics.csv", index=False)
    nonoverlap.to_csv(OUT / "benchmark_metrics_nonoverlap.csv", index=False)
    live.to_csv(OUT / "prospective_forecast.csv", index=False)

    latest = frame.iloc[-1]
    last_halving = pd.Timestamp("2024-04-20", tz="UTC")
    summary = {
        "experiment_id": "btc-price-cycle-baseline-v2",
        "freeze_sha256": FREEZE_SHA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_rows": int(len(frame)),
        "data_start": frame["time"].iloc[0].isoformat(),
        "data_end": frame["time"].iloc[-1].isoformat(),
        "latest_close": float(latest["close"]),
        "days_since_2024_halving": int((latest["time"] - last_halving).days),
        "validation_prediction_rows": int(len(validation)),
        "holdout_prediction_rows": int(len(holdout)),
        "models": sorted(predictions["model"].unique().tolist()),
        "horizons_days": list(HORIZONS),
        "holdout_was_not_used_for_tuning": True,
    }
    (OUT / "run_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("\nHOLDOUT METRICS\n")
    print(metrics[metrics["split"] == "holdout"].to_string(index=False))
    print("\nPROSPECTIVE FORECAST\n")
    print(live.to_string(index=False))


if __name__ == "__main__":
    main()
