from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

import btc_baseline as b


def download_with_daily_tail() -> pd.DataFrame:
    # First run the frozen, checksum-verified monthly loader.
    base = b.download_binance_daily()
    latest = base["time"].iloc[-1].date()
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    if latest >= yesterday:
        return base

    session = requests.Session()
    session.headers.update({"User-Agent": "btc-forecast-lab/0.3-tail"})
    parts = []
    additions = []
    d = latest + timedelta(days=1)
    while d <= yesterday:
        url = f"{b.VISION}/daily/klines/{b.SYMBOL}/{b.INTERVAL}/{b.SYMBOL}-{b.INTERVAL}-{d.isoformat()}.zip"
        raw = b._fetch_zip(url, session)
        if raw is not None:
            parts.append(b._parse_zip(raw))
            additions.append({"url": url, "sha256": b._sha256(raw), "bytes": len(raw)})
        d += timedelta(days=1)

    if not parts:
        return base

    tail = pd.concat(parts, ignore_index=True)
    tail["open_time"] = pd.to_numeric(tail["open_time"], errors="raise")
    tail["time"] = tail["open_time"].map(
        lambda x: pd.to_datetime(int(x), unit="us" if int(x) > 10**14 else "ms", utc=True)
    )
    for c in ("open", "high", "low", "close", "volume"):
        tail[c] = pd.to_numeric(tail[c], errors="raise")
    tail = tail[["time", "open", "high", "low", "close", "volume"]]

    daily = pd.concat([base, tail], ignore_index=True).sort_values("time").drop_duplicates("time", keep="last").reset_index(drop=True)

    gaps = daily["time"].diff().dropna()
    if not (gaps == pd.Timedelta(days=1)).all():
        bad = daily.loc[gaps[gaps != pd.Timedelta(days=1)].index, ["time"]]
        raise RuntimeError(f"BTC daily series has gaps after tail fill: {bad.head().to_dict('records')}")
    if (daily[["open", "high", "low", "close"]] <= 0).any().any():
        raise RuntimeError("Non-positive OHLC value after tail fill")
    if (daily["high"] < daily[["open", "close"]].max(axis=1)).any():
        raise RuntimeError("High below open/close after tail fill")
    if (daily["low"] > daily[["open", "close"]].min(axis=1)).any():
        raise RuntimeError("Low above open/close after tail fill")

    daily.to_csv(b.OUT / "btc_daily.csv", index=False)
    manifest_path = b.OUT / "data_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["rows"] = int(len(daily))
    manifest["start"] = daily["time"].iloc[0].isoformat()
    manifest["end"] = daily["time"].iloc[-1].isoformat()
    manifest["archives"].extend(additions)
    manifest["csv_sha256"] = b._sha256((b.OUT / "btc_daily.csv").read_bytes())
    manifest["daily_tail_fallback"] = True
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return daily


if __name__ == "__main__":
    b.download_binance_daily = download_with_daily_tail
    b.main()
