"""Basic unit tests for risk sizing, filters, bot_state, and US stack."""

from __future__ import annotations

import unittest
import numpy as np
import pandas as pd

from risk_manager import RiskManager
from filters import is_uptrend_df
import bot_state
from strategy import calc_sma, create_strategy, snapshot_signal


class TestCoreBotLogic(unittest.TestCase):
    def test_position_size_respects_risk_and_caps(self):
        rm = RiskManager(market="US")
        qty = rm.calculate_position_size(100_000, price=100.0, stop_distance=2.0)
        self.assertGreater(qty, 0)
        self.assertLessEqual(qty, 100)

    def test_is_uptrend_df(self):
        idx = pd.date_range("2024-01-01", periods=250, freq="D")
        close = pd.Series(np.linspace(100, 150, 250), index=idx)
        df = pd.DataFrame({"close": close, "high": close * 1.01, "low": close * 0.99, "open": close, "volume": 1e6})
        self.assertTrue(is_uptrend_df(df, sma_len=200))
        df2 = df.copy()
        df2["close"] = np.linspace(150, 100, 250)
        self.assertFalse(is_uptrend_df(df2, sma_len=200))

    def test_bot_state_signals_and_sod(self):
        bot_state.reset_sod_for_tests()
        bot_state.publish_signals("US", [{"symbol": "SPY", "signal": "HOLD", "price": 1.0, "reason": "x"}])
        rows = bot_state.get_signals("US", max_age_sec=60)
        self.assertTrue(rows)
        self.assertEqual(rows[0]["symbol"], "SPY")
        sod = bot_state.india_sod_equity(100000)
        self.assertEqual(bot_state.india_sod_equity(101000), sod)
        sod_us = bot_state.us_sod_equity(10000)
        self.assertEqual(bot_state.us_sod_equity(10500), sod_us)

    def test_india_sod_rebases_on_large_deposit(self):
        bot_state.reset_sod_for_tests()
        self.assertEqual(bot_state.india_sod_equity(25_000), 25_000)
        # ₹50k deposit → equity 75k should not look like +200% Daily P&L
        self.assertEqual(bot_state.india_sod_equity(75_000), 75_000)

    def test_trend_strategy_snapshot_on_synthetic(self):
        rng = np.random.default_rng(0)
        n = 260
        close = 100 * np.cumprod(1 + rng.normal(0.001, 0.01, n))
        df = pd.DataFrame({
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(1e5, 1e6, n).astype(float),
        })
        strat = create_strategy("US", name="trend_pullback")
        df = strat.compute_indicators(df)
        snap = snapshot_signal(strat, df, "TEST")
        self.assertIn(snap["signal"], ("BUY", "SELL", "HOLD"))
        self.assertIn("reason", snap)

    def test_calc_sma_length(self):
        s = pd.Series(range(10), dtype=float)
        out = calc_sma(s, 5)
        self.assertTrue(pd.isna(out.iloc[3]))
        self.assertEqual(out.iloc[4], 2.0)


if __name__ == "__main__":
    unittest.main()
