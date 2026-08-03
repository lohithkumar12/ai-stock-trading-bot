"""Basic unit tests for risk sizing, filters, and bot_state."""

from __future__ import annotations

import numpy as np
import pandas as pd

from risk_manager import RiskManager
from filters import is_uptrend_df
import bot_state
from strategy import calc_sma, create_strategy, snapshot_signal


def test_position_size_respects_risk_and_caps():
    rm = RiskManager(market="US")
    # equity 100k, risk 0.75%, stop dist $2 → raw shares = 375, capped by max position pct / shares
    qty = rm.calculate_position_size(100_000, price=100.0, stop_distance=2.0)
    assert qty > 0
    assert qty <= 100  # MAX_SHARES_PER_ORDER default often 50-100 depending on env


def test_is_uptrend_df():
    idx = pd.date_range("2024-01-01", periods=250, freq="D")
    close = pd.Series(np.linspace(100, 150, 250), index=idx)
    df = pd.DataFrame({"close": close, "high": close * 1.01, "low": close * 0.99, "open": close, "volume": 1e6})
    assert is_uptrend_df(df, sma_len=200) is True
    df2 = df.copy()
    df2["close"] = np.linspace(150, 100, 250)
    assert is_uptrend_df(df2, sma_len=200) is False


def test_bot_state_signals_and_sod():
    bot_state.publish_signals("US", [{"symbol": "SPY", "signal": "HOLD", "price": 1.0, "reason": "x"}])
    rows = bot_state.get_signals("US", max_age_sec=60)
    assert rows and rows[0]["symbol"] == "SPY"
    sod = bot_state.india_sod_equity(100000)
    assert bot_state.india_sod_equity(101000) == sod


def test_trend_strategy_snapshot_on_synthetic():
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
    assert snap["signal"] in ("BUY", "SELL", "HOLD")
    assert "reason" in snap


def test_calc_sma_length():
    s = pd.Series(range(10), dtype=float)
    out = calc_sma(s, 5)
    assert pd.isna(out.iloc[3])
    assert out.iloc[4] == 2.0
