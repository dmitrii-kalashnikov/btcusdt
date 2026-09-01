import unittest

import pandas as pd

import macro_pit as m
from macro_pit_runner_v4 import EXCLUDED, configure_v11, make_weekly_origins_utc, vintage_from_column


class MacroRuntimeV4Tests(unittest.TestCase):
    def test_v11_excludes_only_unavailable_hy_source(self):
        original = dict(m.SERIES)
        try:
            configure_v11()
            self.assertNotIn("BAMLH0A0HYM2", m.SERIES)
            self.assertEqual(EXCLUDED, {"BAMLH0A0HYM2"})
            self.assertEqual(len(m.SERIES), 15)
        finally:
            m.SERIES = original

    def test_compact_vintage(self):
        self.assertEqual(vintage_from_column("DGS10_20260831"), pd.Timestamp("2026-08-31", tz="UTC"))

    def test_origin_end_is_utc(self):
        out = make_weekly_origins_utc(pd.Timestamp("2026-08-31"))
        self.assertEqual(out[-1], pd.Timestamp("2026-08-31", tz="UTC"))


if __name__ == "__main__":
    unittest.main()
