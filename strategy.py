"""
strategy.py — Trading Strategy Module
========================================
Implements a Low-Risk Mean Reversion + Smart DCA strategy.
"""

import logging
import numpy as np
import pandas as pd
import config

logger = logging.getLogger(__name__)


def calc_sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length, min_periods=length).mean()


def calc_rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calc_bbands(series: pd.Series, length: int = 20, std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = series.rolling(window=length, min_periods=length).mean()
    rolling_std = series.rolling(window=length, min_periods=length).std()
    upper = middle + (std * rolling_std)
    lower = middle - (std * rolling_std)
    return lower, middle, upper


class Strategy:
    def __init__(self):
        self.sma_slow = config.SMA_SLOW
        self.sma_fast = config.SMA_FAST
        self.rsi_period = config.RSI_PERIOD
        self.rsi_buy = config.RSI_BUY_THRESHOLD
        self.rsi_sell = config.RSI_SELL_THRESHOLD
        self.bb_std = config.BB_STD_DEV
        logger.info(
            f"Strategy initialized -- "
            f"SMA({self.sma_slow}/{self.sma_fast}), "
            f"RSI({self.rsi_period}, buy<{self.rsi_buy}, sell>{self.rsi_sell}), "
            f"BB(std={self.bb_std})"
        )

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df[f"SMA_{self.sma_slow}"] = calc_sma(df["close"], self.sma_slow)
        df[f"SMA_{self.sma_fast}"] = calc_sma(df["close"], self.sma_fast)
        df[f"RSI_{self.rsi_period}"] = calc_rsi(df["close"], self.rsi_period)
        bbl, bbm, bbu = calc_bbands(df["close"], self.sma_fast, self.bb_std)
        df["BBL"] = bbl
        df["BBM"] = bbm
        df["BBU"] = bbu
        return df

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> str:
        # TEST_MODE fake buys are disabled permanently for live capital safety
        if config.TEST_MODE:
            logger.error(f"{symbol}: TEST_MODE is on — refusing signal generation.")
            return "HOLD"

        if len(df) < self.sma_slow + 1:
            logger.warning(f"{symbol}: Not enough data ({len(df)} bars) for {self.sma_slow}-period SMA. Signal -> HOLD.")
            return "HOLD"

        latest = df.iloc[-1]
        close    = latest["close"]
        sma_slow = latest.get(f"SMA_{self.sma_slow}")
        rsi      = latest.get(f"RSI_{self.rsi_period}")
        bbl      = latest.get("BBL")
        bbu      = latest.get("BBU")

        if pd.isna(sma_slow) or pd.isna(rsi) or pd.isna(bbl) or pd.isna(bbu):
            logger.debug(f"{symbol}: Indicators contain NaN -- Signal -> HOLD.")
            return "HOLD"

        logger.info(
            f"{symbol} Indicators | Close={close:.2f} | "
            f"SMA{self.sma_slow}={sma_slow:.2f} | RSI={rsi:.1f} | "
            f"BBL={bbl:.2f} | BBU={bbu:.2f}"
        )

        if close > sma_slow and rsi < self.rsi_buy and close <= bbl:
            logger.info(f"[BUY SIGNAL] {symbol} -- Uptrend + Oversold + Lower BB touch")
            return "BUY"

        # Strict sell: need BOTH overbought RSI and upper BB (fewer noise exits)
        if config.STRICT_SELL:
            if rsi > self.rsi_sell and close >= bbu:
                logger.info(f"[SELL SIGNAL] {symbol} -- Overbought AND Upper BB touch")
                return "SELL"
        else:
            if rsi > self.rsi_sell or close >= bbu:
                logger.info(f"[SELL SIGNAL] {symbol} -- Overbought or Upper BB touch")
                return "SELL"

        return "HOLD"
