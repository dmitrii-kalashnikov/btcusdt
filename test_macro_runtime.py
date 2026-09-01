import unittest

import pandas as pd

from macro_pit_runner import make_weekly_origins_utc


class MacroRuntimeTests(unittest.TestCase):
    def test_weekly_origins_accept_utc_aware_end(self):
        end = pd.Timestamp("2026-08-31", tz="UTC")
        out = make_weekly_origins_utc(end)
        self.assertEqual(str(out.tz), "UTC")
        self.assertEqual(out[-1], end)
        self.assertEqual(out[0], pd.Timestamp("2018-01-01", tz="UTC"))

    def test_weekly_origins_accept_naive_end(self):
        end = pd.Timestamp("2026-08-31")
        out = make_weekly_origins_utc(end)
        self.assertEqual(out[-1], pd.Timestamp("2026-08-31", tz="UTC"))


if __name__ == "__main__":
    unittest.main()
