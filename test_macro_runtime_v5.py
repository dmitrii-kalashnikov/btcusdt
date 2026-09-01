import unittest

import pandas as pd

import macro_pit as m
from macro_pit_runner_v5 import EXCLUDED, LOOKBACK_DAYS, configure_v11, make_weekly_origins_utc, vintage_from_column


class MacroRuntimeV5Tests(unittest.TestCase):
    def test_source_contract(self):
        original = dict(m.SERIES)
        try:
            configure_v11()
            self.assertEqual(EXCLUDED, {"BAMLH0A0HYM2"})
            self.assertEqual(len(m.SERIES), 15)
            self.assertNotIn("BAMLH0A0HYM2", m.SERIES)
        finally:
            m.SERIES = original

    def test_retrieval_lookback_is_bounded(self):
        self.assertEqual(LOOKBACK_DAYS, 400)

    def test_compact_vintage(self):
        self.assertEqual(vintage_from_column("SP500_20180101"), pd.Timestamp("2018-01-01", tz="UTC"))

    def test_utc_origins(self):
        out = make_weekly_origins_utc(pd.Timestamp("2026-08-31"))
        self.assertEqual(out[-1], pd.Timestamp("2026-08-31", tz="UTC"))


if __name__ == "__main__":
    unittest.main()
