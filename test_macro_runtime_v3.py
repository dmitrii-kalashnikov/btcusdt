import unittest

import pandas as pd

from macro_pit_runner_v3 import make_weekly_origins_utc, vintage_from_column


class MacroRuntimeV3Tests(unittest.TestCase):
    def test_compact_alfred_vintage_column(self):
        self.assertEqual(
            vintage_from_column("M2SL_20180101"),
            pd.Timestamp("2018-01-01", tz="UTC"),
        )

    def test_separated_vintage_column(self):
        self.assertEqual(
            vintage_from_column("M2SL_2018-01-01"),
            pd.Timestamp("2018-01-01", tz="UTC"),
        )

    def test_non_vintage_column(self):
        self.assertIsNone(vintage_from_column("date"))

    def test_weekly_origins_utc(self):
        end = pd.Timestamp("2026-08-31", tz="UTC")
        out = make_weekly_origins_utc(end)
        self.assertEqual(out[0], pd.Timestamp("2018-01-01", tz="UTC"))
        self.assertEqual(out[-1], end)


if __name__ == "__main__":
    unittest.main()
