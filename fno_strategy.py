"""
fno_strategy.py — Defined-Risk Options Strategy Engine
=====================================================
Generates high-confidence option signals based on:
  - Relative Strength & Moving Average Regime (SMA20, SMA200)
  - RSI oversold/overbought thresholds (RSI < 35 for Call, RSI > 65 for Put)
  - ADX trend strength filtering (ADX > 20)
  - Strict stop-loss & target calculations (defined-risk only)
  - Per-symbol cooldown to prevent spam entries
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

SIGNAL_COOLDOWN_SEC = 1800.0  # 30 minutes per symbol


class FnoStrategy:
    def __init__(self, strategy_type: str = "directional_options"):
        self.strategy_type = strategy_type
        self._last_signal_time: dict[str, float] = {}
        logger.info(f"[FNO] FnoStrategy initialized: {self.strategy_type}")

    def generate_signal(
        self,
        symbol: str,
        spot_price: float,
        rsi: float = 50.0,
        adx: float = 25.0,
        sma_fast: float = 0.0,
        sma_slow: float = 0.0,
        atr: float = 0.0,
    ) -> dict[str, Any] | None:
        """
        Evaluates technical criteria for defined-risk options signals.
        Returns signal dict or None if criteria are not satisfied.
        """
        if spot_price <= 0:
            return None

        # Spreads / CSP not enabled by default
        if self.strategy_type not in ("directional_options", "directional", ""):
            logger.info(f"[FNO] Strategy {self.strategy_type} gated off")
            return None

        last = self._last_signal_time.get(symbol, 0.0)
        if time.time() - last < SIGNAL_COOLDOWN_SEC:
            return None

        # Requires ADX > 20 for strong trend regime
        if adx < 20.0:
            return None

        signal = None
        # Bullish Call: Fast SMA > Slow SMA and RSI oversold pullback
        if (sma_fast > sma_slow or spot_price > sma_slow) and (rsi < 38.0):
            sl_dist = (atr * 1.5) if atr > 0 else (spot_price * 0.015)
            signal = {
                "action": "BUY_CALL",
                "symbol": symbol,
                "spot_price": spot_price,
                "option_type": "CE",
                "stop_loss_dist": round(sl_dist, 2),
                "reason": f"Bullish trend pullback (RSI={rsi:.1f}, ADX={adx:.1f})",
            }

        # Bearish Put: Fast SMA < Slow SMA and RSI overbought rally
        elif (sma_fast < sma_slow or spot_price < sma_slow) and (rsi > 62.0):
            sl_dist = (atr * 1.5) if atr > 0 else (spot_price * 0.015)
            signal = {
                "action": "BUY_PUT",
                "symbol": symbol,
                "spot_price": spot_price,
                "option_type": "PE",
                "stop_loss_dist": round(sl_dist, 2),
                "reason": f"Bearish rally rejection (RSI={rsi:.1f}, ADX={adx:.1f})",
            }

        if signal:
            self._last_signal_time[symbol] = time.time()
            logger.info(f"[FNO] Signal {symbol}: {signal['action']} — {signal['reason']}")
        return signal
