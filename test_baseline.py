import unittest

import numpy as np
import pandas as pd

import btc_baseline as b


class LeakageTests(unittest.TestCase):
    def test_future_targets_cannot_change_prediction(self):
        n = 2300
        t = pd.date_range("2018-01-01", periods=n, freq="D", tz="UTC")
        # deterministic but nontrivial synthetic series
        x = np.arange(n, dtype=float)
        close = 5000.0 * np.exp(0.0005 * x + 0.08 * np.sin(x / 55.0))
        raw = pd.DataFrame({
            "time": t,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.ones(n),
        })
        frame = b.add_features_targets(raw)
        i, h = 2000, 90
        p1 = b._predict_one(frame, i, h)

        poisoned = frame.copy()
        poisoned.loc[i - h + 1 :, f"fwd_ret_{h}d"] = 999.0
        p2 = b._predict_one(poisoned, i, h)

        for name in ("constant_mean", "momentum", "four_year_cycle", "ridge_price", "equal_weight_ensemble"):
            self.assertAlmostEqual(p1[name], p2[name], places=12)

    def test_cycle_analog_is_four_calendar_years_back(self):
        n = 2600
        t = pd.date_range("2018-01-01", periods=n, freq="D", tz="UTC")
        close = np.exp(np.linspace(8.0, 9.0, n))
        raw = pd.DataFrame({
            "time": t,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.ones(n),
        })
        frame = b.add_features_targets(raw)
        i, h = 2200, 30
        analog_time = frame.at[i, "time"] - pd.DateOffset(years=4)
        analog_i = int(frame.index[frame["time"] == analog_time][0])
        expected = float(frame.at[analog_i, f"fwd_ret_{h}d"])
        got = b._predict_one(frame, i, h)["four_year_cycle"]
        self.assertAlmostEqual(expected, got, places=12)


if __name__ == "__main__":
    unittest.main()
