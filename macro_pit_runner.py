from __future__ import annotations

import pandas as pd

import macro_pit as m


def make_weekly_origins_utc(last_date: pd.Timestamp) -> pd.DatetimeIndex:
    end = pd.to_datetime(last_date, utc=True).normalize()
    start = pd.Timestamp("2018-01-01", tz="UTC")
    d = pd.date_range(start=start, end=end, freq="7D")
    if len(d) == 0 or d[-1] != end:
        d = d.append(pd.DatetimeIndex([end]))
    return d.unique().sort_values()


def main() -> None:
    m.make_weekly_origins = make_weekly_origins_utc
    m.main()


if __name__ == "__main__":
    main()
