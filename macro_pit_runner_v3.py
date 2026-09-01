from __future__ import annotations

import re

import pandas as pd

import macro_pit as m


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
        return pd.Timestamp(
            f"{compact.group(1)}-{compact.group(2)}-{compact.group(3)}",
            tz="UTC",
        )
    separated = re.search(r"((?:19|20)\d{2})[-_](\d{2})[-_](\d{2})$", text)
    if separated:
        return pd.Timestamp(
            f"{separated.group(1)}-{separated.group(2)}-{separated.group(3)}",
            tz="UTC",
        )
    return None


def main() -> None:
    m.make_weekly_origins = make_weekly_origins_utc
    m.Fred._vintage_from_col = staticmethod(vintage_from_column)
    m.main()


if __name__ == "__main__":
    main()
