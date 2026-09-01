from __future__ import annotations

import json
import re

import pandas as pd

import macro_pit as m

FREEZE_SHA = "932bba5b154b6f11659e89eaae4c3b66e1c9b4f4d9b86a2137fbd869d909dd12"
EXCLUDED = {"BAMLH0A0HYM2"}


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


def configure_v11() -> None:
    m.FREEZE_PATH = m.Path("MACRO_FREEZE_v1_1.json")
    m.EXPECTED_FREEZE_SHA = FREEZE_SHA
    m.SERIES = {sid: name for sid, name in m.SERIES.items() if sid not in EXCLUDED}
    m.GROWTH_SERIES = {"M2SL", "WALCL", "WTREGEN", "DTWEXBGS", "SP500", "NASDAQCOM", "CPIAUCSL", "PAYEMS"}
    m.LEVEL_SERIES = set(m.SERIES) - m.GROWTH_SERIES
    m.make_weekly_origins = make_weekly_origins_utc
    m.Fred._vintage_from_col = staticmethod(vintage_from_column)


def relabel_summary() -> None:
    path = m.OUT / "macro_run_summary.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text())
    payload["experiment_id"] = "btc-macro-pit-v1.1"
    payload["source_exclusions"] = sorted(EXCLUDED)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def main() -> None:
    configure_v11()
    m.main()
    relabel_summary()


if __name__ == "__main__":
    main()
