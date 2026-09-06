import unittest

import pandas as pd

import macro_pit as m
from macro_pit_runner import EXCLUDED, LOOKBACK_DAYS, configure_v12, make_weekly_origins_utc, vintage_from_column


class MacroRuntimeTests(unittest.TestCase):
    def test_source_contract(self):
        original = dict(m.SERIES)
        original_growth = set(m.GROWTH_SERIES)
        original_level = set(m.LEVEL_SERIES)
        try:
            configure_v12()
            self.assertEqual(EXCLUDED, {"BAMLH0A0HYM2", "SP500"})
            self.assertEqual(len(m.SERIES), 14)
            self.assertNotIn("BAMLH0A0HYM2", m.SERIES)
            self.assertNotIn("SP500", m.SERIES)
            self.assertIn("NASDAQCOM", m.SERIES)
        finally:
            m.SERIES = original
            m.GROWTH_SERIES = original_growth
            m.LEVEL_SERIES = original_level

    def test_retrieval_lookback_is_bounded(self):
        self.assertEqual(LOOKBACK_DAYS, 400)

    def test_compact_vintage(self):
        self.assertEqual(vintage_from_column("NASDAQCOM_20180101"), pd.Timestamp("2018-01-01", tz="UTC"))

    def test_weekly_origins_accept_utc_aware_end(self):
        end = pd.Timestamp("2026-08-31", tz="UTC")
        out = make_weekly_origins_utc(end)
        self.assertEqual(str(out.tz), "UTC")
        self.assertEqual(out[-1], end)
        self.assertEqual(out[0], pd.Timestamp("2018-01-01", tz="UTC"))

    def test_weekly_origins_accept_naive_end(self):
        out = make_weekly_origins_utc(pd.Timestamp("2026-08-31"))
        self.assertEqual(out[-1], pd.Timestamp("2026-08-31", tz="UTC"))


if __name__ == "__main__":
    unittest.main()
