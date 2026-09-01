from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import btc_baseline as base
from run_baseline_fresh import download_with_daily_tail

FRED_API = "https://api.stlouisfed.org/fred"
OUT = Path("macro_artifacts")
OUT.mkdir(exist_ok=True)
FREEZE_PATH = Path("MACRO_FREEZE_v1.json")
EXPECTED_FREEZE_SHA = "15356ae0d97285bd14bb71a04bc19fd9fd27be0b0877884318c490453d78ed96"

SERIES = {
    "M2SL": "m2",
    "WALCL": "fed_assets",
    "WTREGEN": "tga",
    "RRPONTSYD": "rrp",
    "DFF": "fed_funds",
    "DGS2": "ust_2y",
    "DGS10": "ust_10y",
    "DFII10": "real_10y",
    "DTWEXBGS": "broad_usd",
    "BAMLH0A0HYM2": "hy_oas",
    "VIXCLS": "vix",
    "SP500": "sp500",
    "NASDAQCOM": "nasdaq",
    "CPIAUCSL": "cpi",
    "UNRATE": "unemployment",
    "PAYEMS": "payrolls",
}
GROWTH_SERIES = {"M2SL", "WALCL", "WTREGEN", "DTWEXBGS", "SP500", "NASDAQCOM", "CPIAUCSL", "PAYEMS"}
LEVEL_SERIES = set(SERIES) - GROWTH_SERIES
PRICE_FEATURES = [
    "ret_7d", "ret_30d", "ret_90d", "ret_180d", "ret_365d",
    "rv_30d", "rv_90d", "dist_ma_50", "dist_ma_200", "drawdown_from_ath",
]
HORIZONS = (7, 30, 90, 180, 365)
ALPHA = 50.0


def canonical_manifest_sha(path: Path) -> str:
    payload = json.loads(path.read_text())
    blob = json.dumps(payload["manifest"], sort_keys=True, separators=(",", ":")).encode()
    actual = hashlib.sha256(blob).hexdigest()
    if payload.get("sha256") != actual or actual != EXPECTED_FREEZE_SHA:
        raise RuntimeError("Macro freeze canonical SHA mismatch")
    return actual


class Fred:
    def __init__(self) -> None:
        self.api_key = os.getenv("FRED_API_KEY", "")
        if not re.fullmatch(r"[a-z0-9]{32}", self.api_key):
            raise RuntimeError("FRED_API_KEY is missing or invalid format")
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "btc-forecast-lab-macro/1.0"})

    def get(self, endpoint: str, params: dict) -> dict:
        q = dict(params)
        q["api_key"] = self.api_key
        q["file_type"] = "json"
        try:
            r = self.s.get(f"{FRED_API}/{endpoint}", params=q, timeout=90)
        except requests.RequestException:
            raise RuntimeError(f"FRED transport failure; endpoint={endpoint}") from None
        if r.status_code >= 400:
            raise RuntimeError(f"FRED HTTP {r.status_code}; endpoint={endpoint}")
        try:
            return r.json()
        except Exception:
            raise RuntimeError(f"FRED invalid JSON; endpoint={endpoint}") from None

    def metadata(self, sid: str) -> dict:
        p = self.get("series", {"series_id": sid})
        rows = p.get("seriess", [])
        if not rows:
            raise RuntimeError(f"No FRED metadata for {sid}")
        row = rows[0]
        return {
            "series_id": sid,
            "title": row.get("title"),
            "frequency": row.get("frequency"),
            "units": row.get("units"),
            "seasonal_adjustment": row.get("seasonal_adjustment"),
            "last_updated": row.get("last_updated"),
        }

    @staticmethod
    def _vintage_from_col(col: str) -> pd.Timestamp | None:
        m = re.search(r"((?:19|20)\d{2})[-_](\d{2})[-_](\d{2})$", str(col))
        if not m:
            return None
        return pd.Timestamp(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", tz="UTC")

    def snapshots(self, sid: str, vintage_dates: pd.DatetimeIndex, chunk_size: int = 75) -> pd.DataFrame:
        out = []
        strings = [d.strftime("%Y-%m-%d") for d in vintage_dates]
        for pos in range(0, len(strings), chunk_size):
            chunk = strings[pos:pos + chunk_size]
            first = pd.Timestamp(chunk[0]) - pd.Timedelta(days=730)
            last = pd.Timestamp(chunk[-1])
            payload = self.get(
                "series/observations",
                {
                    "series_id": sid,
                    "vintage_dates": ",".join(chunk),
                    "observation_start": first.strftime("%Y-%m-%d"),
                    "observation_end": last.strftime("%Y-%m-%d"),
                    "output_type": 2,
                    "limit": 100000,
                },
            )
            rows = payload.get("observations", [])
            if not rows:
                continue
            raw = pd.DataFrame(rows)
            if "date" not in raw.columns:
                raise RuntimeError(f"Unexpected FRED output_type=2 schema for {sid}: missing date")
            obs_date = pd.to_datetime(raw["date"], utc=True, errors="coerce")

            vintage_cols = []
            for c in raw.columns:
                v = self._vintage_from_col(c)
                if v is not None:
                    vintage_cols.append((c, v))

            if vintage_cols:
                for col, vintage in vintage_cols:
                    vals = pd.to_numeric(raw[col].replace(".", pd.NA), errors="coerce")
                    valid = vals.notna() & obs_date.notna() & (obs_date <= vintage)
                    if not valid.any():
                        continue
                    j = obs_date[valid].idxmax()
                    out.append({
                        "forecast_time": vintage,
                        "series_id": sid,
                        "value": float(vals.loc[j]),
                        "observation_time": obs_date.loc[j],
                        "available_at": vintage,
                    })
                continue

            if {"value", "realtime_start"}.issubset(raw.columns):
                vals = pd.to_numeric(raw["value"].replace(".", pd.NA), errors="coerce")
                rt = pd.to_datetime(raw["realtime_start"], utc=True, errors="coerce")
                alt = pd.DataFrame({"obs": obs_date, "vintage": rt, "value": vals}).dropna()
                requested = set(pd.to_datetime(chunk, utc=True))
                for vintage, g in alt[alt["vintage"].isin(requested)].groupby("vintage"):
                    g = g[g["obs"] <= vintage]
                    if g.empty:
                        continue
                    r = g.loc[g["obs"].idxmax()]
                    out.append({
                        "forecast_time": vintage,
                        "series_id": sid,
                        "value": float(r["value"]),
                        "observation_time": r["obs"],
                        "available_at": vintage,
                    })
                continue

            safe_cols = [str(c) for c in raw.columns if c not in {"value"}][:12]
            raise RuntimeError(f"Unrecognized FRED output_type=2 schema for {sid}; cols={safe_cols}")

        frame = pd.DataFrame(out)
        if frame.empty:
            raise RuntimeError(f"No point-in-time snapshots returned for {sid}")
        frame = frame.sort_values("forecast_time").drop_duplicates(["forecast_time", "series_id"], keep="last")
        if (frame["available_at"] > frame["forecast_time"]).any():
            raise RuntimeError(f"Future macro availability detected for {sid}")
        return frame.reset_index(drop=True)


def validate_net_liquidity_units(meta: pd.DataFrame) -> None:
    units = dict(zip(meta["series_id"], meta["units"].fillna("")))
    if "million" not in units.get("WALCL", "").lower():
        raise RuntimeError("Unexpected WALCL units; cannot form net liquidity")
    if "million" not in units.get("WTREGEN", "").lower():
        raise RuntimeError("Unexpected WTREGEN units; cannot form net liquidity")
    if "billion" not in units.get("RRPONTSYD", "").lower():
        raise RuntimeError("Unexpected RRPONTSYD units; cannot form net liquidity")


def build_macro_features(long: pd.DataFrame, meta: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    pivot = long.pivot(index="forecast_time", columns="series_id", values="value").sort_index()
    obs = long.pivot(index="forecast_time", columns="series_id", values="observation_time").sort_index()
    pivot = pivot.rename(columns=SERIES)
    obs = obs.rename(columns={k: f"{v}__observation_time" for k, v in SERIES.items()})
    frame = pivot.join(obs)
    macro_features = []

    for sid in GROWTH_SERIES:
        name = SERIES[sid]
        x = pd.to_numeric(frame[name], errors="coerce")
        logx = np.log(x.where(x > 0))
        for lag in (13, 52):
            col = f"{name}_logchg_{lag}w"
            frame[col] = logx.diff(lag)
            macro_features.append(col)

    for sid in LEVEL_SERIES:
        name = SERIES[sid]
        x = pd.to_numeric(frame[name], errors="coerce")
        macro_features.append(name)
        for lag in (13, 52):
            col = f"{name}_delta_{lag}w"
            frame[col] = x.diff(lag)
            macro_features.append(col)

    frame["yield_curve_10y_2y"] = frame["ust_10y"] - frame["ust_2y"]
    frame["breakeven_proxy_10y"] = frame["ust_10y"] - frame["real_10y"]
    macro_features += ["yield_curve_10y_2y", "breakeven_proxy_10y"]

    validate_net_liquidity_units(meta)
    frame["net_liquidity_musd"] = frame["fed_assets"] - frame["tga"] - 1000.0 * frame["rrp"]
    nl = np.log(frame["net_liquidity_musd"].where(frame["net_liquidity_musd"] > 0))
    frame["net_liquidity_logchg_13w"] = nl.diff(13)
    frame["net_liquidity_logchg_52w"] = nl.diff(52)
    macro_features += ["net_liquidity_logchg_13w", "net_liquidity_logchg_52w"]

    for sid, name in SERIES.items():
        ocol = f"{name}__observation_time"
        age = (frame.index.to_series(index=frame.index) - pd.to_datetime(frame[ocol], utc=True)).dt.days
        frame[f"{name}__staleness_days"] = age.values
        if (age.dropna() < 0).any():
            raise RuntimeError(f"Negative staleness for {sid}")

    return frame.reset_index(), macro_features


def ridge() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("ridge", Ridge(alpha=ALPHA)),
    ])


def p_up(mu: float, sigma: float) -> float:
    if not np.isfinite(sigma) or sigma <= 1e-12:
        return 0.5
    return 0.5 * (1.0 + math.erf((mu / sigma) / math.sqrt(2.0)))


def make_weekly_origins(last_date: pd.Timestamp) -> pd.DatetimeIndex:
    d = pd.date_range("2018-01-01", last_date.normalize(), freq="7D", tz="UTC")
    if len(d) == 0 or d[-1] != last_date.normalize():
        d = d.append(pd.DatetimeIndex([last_date.normalize()]))
    return d.unique().sort_values()


def prepare_model_frame(btc: pd.DataFrame, macro: pd.DataFrame) -> pd.DataFrame:
    feat = base.add_features_targets(btc)
    feat = feat.set_index("time")
    m = macro.set_index("forecast_time")
    common = m.index.intersection(feat.index)
    frame = feat.loc[common].join(m.loc[common], how="inner").reset_index().rename(columns={"index": "time"})
    return frame.sort_values("time").reset_index(drop=True)


def predict_origin(frame: pd.DataFrame, i: int, h: int, features: list[str]) -> tuple[float, float]:
    t = frame.at[i, "time"]
    cutoff = t - pd.Timedelta(days=h)
    target = f"fwd_ret_{h}d"
    train = frame[(frame["time"] <= cutoff) & frame[target].notna()].copy()
    if len(train) < 100:
        return float("nan"), float("nan")
    model = ridge()
    model.fit(train[features], train[target])
    mu = float(model.predict(frame.loc[[i], features])[0])
    sigma = float(train[target].std(ddof=1))
    return mu, sigma


def evaluate(frame: pd.DataFrame, macro_features: list[str]) -> pd.DataFrame:
    rows = []
    price_only = PRICE_FEATURES
    price_macro = PRICE_FEATURES + macro_features
    periods = {
        "validation": (pd.Timestamp("2022-01-01", tz="UTC"), pd.Timestamp("2023-12-31 23:59:59", tz="UTC")),
        "secondary_consumed_backtest": (pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2025-12-31 23:59:59", tz="UTC")),
    }
    for split, (start, end) in periods.items():
        for i, row in frame.iterrows():
            t = row["time"]
            if not (start <= t <= end):
                continue
            for h in HORIZONS:
                actual = row.get(f"fwd_ret_{h}d")
                if pd.isna(actual):
                    continue
                for model_name, cols in (("price_ridge", price_only), ("price_macro_ridge", price_macro)):
                    mu, sigma = predict_origin(frame, i, h, cols)
                    if not np.isfinite(mu):
                        continue
                    spot = float(row["close"])
                    rows.append({
                        "split": split,
                        "time": t,
                        "horizon_days": h,
                        "model": model_name,
                        "prediction_log_return": mu,
                        "actual_log_return": float(actual),
                        "p_up": p_up(mu, sigma),
                        "actual_up": float(actual > 0),
                        "spot": spot,
                        "forecast_price": spot * math.exp(mu),
                        "actual_future_price": spot * math.exp(float(actual)),
                    })
    return pd.DataFrame(rows)


def score(pred: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (split, h, model), g in pred.groupby(["split", "horizon_days", "model"]):
        err = g["prediction_log_return"] - g["actual_log_return"]
        rows.append({
            "split": split,
            "horizon_days": int(h),
            "model": model,
            "n": int(len(g)),
            "directional_accuracy": float((np.sign(g["prediction_log_return"]) == np.sign(g["actual_log_return"])).mean()),
            "mae_log_return": float(np.abs(err).mean()),
            "rmse_log_return": float(np.sqrt(np.mean(err ** 2))),
            "brier_up": float(((g["p_up"] - g["actual_up"]) ** 2).mean()),
        })
    return pd.DataFrame(rows).sort_values(["split", "horizon_days", "model"])


def prospective(frame: pd.DataFrame, macro_features: list[str]) -> pd.DataFrame:
    i = len(frame) - 1
    row = frame.iloc[i]
    t = row["time"]
    spot = float(row["close"])
    rows = []
    for h in HORIZONS:
        for model_name, cols in (("price_ridge", PRICE_FEATURES), ("price_macro_ridge", PRICE_FEATURES + macro_features)):
            mu, sigma = predict_origin(frame, i, h, cols)
            rows.append({
                "as_of": t,
                "forecast_date": t + pd.Timedelta(days=h),
                "horizon_days": h,
                "model": model_name,
                "spot": spot,
                "predicted_return_pct": math.exp(mu) - 1.0,
                "forecast_price": spot * math.exp(mu),
                "p_up": p_up(mu, sigma),
            })
    return pd.DataFrame(rows)


def main() -> None:
    freeze_sha = canonical_manifest_sha(FREEZE_PATH)
    base.download_binance_daily = download_with_daily_tail
    btc = download_with_daily_tail()
    last = btc["time"].iloc[-1]
    vintages = make_weekly_origins(last)

    fred = Fred()
    meta_rows = [fred.metadata(sid) for sid in SERIES]
    meta = pd.DataFrame(meta_rows)
    meta.to_csv(OUT / "fred_series_metadata.csv", index=False)

    parts = []
    for sid in SERIES:
        snap = fred.snapshots(sid, vintages)
        parts.append(snap)
        print(f"PIT {sid}: {len(snap)} snapshots; latest_obs={snap['observation_time'].max().date()}")
    long = pd.concat(parts, ignore_index=True)
    long.to_csv(OUT / "fred_pit_snapshots_long.csv", index=False)

    macro, macro_features = build_macro_features(long, meta)
    macro.to_csv(OUT / "macro_weekly_features.csv", index=False)
    frame = prepare_model_frame(btc, macro)

    if (pd.to_datetime(long["available_at"], utc=True) > pd.to_datetime(long["forecast_time"], utc=True)).any():
        raise RuntimeError("Macro look-ahead invariant failed")

    pred = evaluate(frame, macro_features)
    metrics = score(pred)
    live = prospective(frame, macro_features)
    pred.to_csv(OUT / "macro_predictions.csv", index=False)
    metrics.to_csv(OUT / "macro_metrics.csv", index=False)
    live.to_csv(OUT / "macro_prospective_forecast.csv", index=False)

    coverage = long.groupby("series_id").agg(
        snapshots=("forecast_time", "size"),
        first_vintage=("forecast_time", "min"),
        last_vintage=("forecast_time", "max"),
        latest_observation=("observation_time", "max"),
    ).reset_index()
    coverage.to_csv(OUT / "macro_coverage.csv", index=False)

    manifest = {
        "experiment_id": "btc-macro-pit-v1",
        "freeze_sha256": freeze_sha,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "btc_data_end": last.isoformat(),
        "btc_latest_close": float(btc["close"].iloc[-1]),
        "weekly_origins": int(len(vintages)),
        "macro_series_count": len(SERIES),
        "macro_feature_count": len(macro_features),
        "point_in_time_rule": "available_at <= forecast_time",
        "secondary_2024_2025_is_pristine_holdout": False,
    }
    (OUT / "macro_run_summary.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(json.dumps(manifest, indent=2, sort_keys=True))
    print("\nVALIDATION METRICS 2022-2023\n")
    print(metrics[metrics["split"] == "validation"].to_string(index=False))
    print("\nSECONDARY CONSUMED BACKTEST 2024-2025\n")
    print(metrics[metrics["split"] == "secondary_consumed_backtest"].to_string(index=False))
    print("\nPROSPECTIVE MACRO FORECAST\n")
    print(live.to_string(index=False))


if __name__ == "__main__":
    main()
