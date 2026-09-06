from __future__ import annotations

import json
import re

import pandas as pd

import macro_pit as m

FREEZE_SHA = "6af1b586910fd3b7dc7c9f858b3c412866507a8c7bf4f9c96193c61209a6d4b1"
EXCLUDED = {"BAMLH0A0HYM2", "SP500"}
LOOKBACK_DAYS = 400


def make_weekly_origins_utc(last_date: pd.Timestamp) -> pd.DatetimeIndex:
    end = pd.to_datetime(last_date, utc=True).normalize()
    start = pd.Timestamp("2018-01-01", tz="UTC")
    d = pd.date_range(start=start, end=end, freq="7D")
    if len(d) == 0 or d[-1] != end:
        d = d.append(pd.DatetimeIndex([end]))
    return d.unique().sort_values()


def vintage_from_column(col: str) -> pd.Timestamp | None:
    text = str(col)
    compact = re.search(r"((?:19|20)\d{2})(\d{2})(\d{2})$", text)
    if compact:
        return pd.Timestamp(f"{compact.group(1)}-{compact.group(2)}-{compact.group(3)}", tz="UTC")
    separated = re.search(r"((?:19|20)\d{2})[-_](\d{2})[-_](\d{2})$", text)
    if separated:
        return pd.Timestamp(f"{separated.group(1)}-{separated.group(2)}-{separated.group(3)}", tz="UTC")
    return None


def snapshots_bounded(self, sid: str, vintage_dates: pd.DatetimeIndex, chunk_size: int = 75) -> pd.DataFrame:
    out = []
    strings = [d.strftime("%Y-%m-%d") for d in vintage_dates]
    for pos in range(0, len(strings), chunk_size):
        chunk = strings[pos:pos + chunk_size]
        first = pd.Timestamp(chunk[0]) - pd.Timedelta(days=LOOKBACK_DAYS)
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
            v = vintage_from_column(c)
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


def configure_v12() -> None:
    m.FREEZE_PATH = m.Path("MACRO_FREEZE_v1_2.json")
    m.EXPECTED_FREEZE_SHA = FREEZE_SHA
    m.SERIES = {sid: name for sid, name in m.SERIES.items() if sid not in EXCLUDED}
    m.GROWTH_SERIES = {"M2SL", "WALCL", "WTREGEN", "DTWEXBGS", "NASDAQCOM", "CPIAUCSL", "PAYEMS"}
    m.LEVEL_SERIES = set(m.SERIES) - m.GROWTH_SERIES
    m.make_weekly_origins = make_weekly_origins_utc
    m.Fred._vintage_from_col = staticmethod(vintage_from_column)
    m.Fred.snapshots = snapshots_bounded


def relabel_summary() -> None:
    path = m.OUT / "macro_run_summary.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text())
    payload["experiment_id"] = "btc-macro-pit-v1.2"
    payload["source_exclusions"] = sorted(EXCLUDED)
    payload["alfred_snapshot_lookback_days"] = LOOKBACK_DAYS
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def main() -> None:
    configure_v12()
    m.main()
    relabel_summary()


if __name__ == "__main__":
    main()
