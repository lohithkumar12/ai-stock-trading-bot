"""
data_feed.py — Market Data Feed Module
========================================
Fetches historical bar data and real-time quotes from Alpaca's Stock Data API.
Uses the official alpaca-py SDK's StockHistoricalDataClient.

Includes per-symbol bar cache, inter-call throttle, and 429 retry/backoff
so the trading loop + dashboard scanner do not burn the Alpaca rate limit.
"""

import logging
import time
from datetime import datetime, timedelta

import pandas as pd
from alpaca.common.exceptions import APIError
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

import config

logger = logging.getLogger(__name__)

TIMEFRAME_MAP: dict[str, TimeFrame] = {
    "1Min":  TimeFrame.Minute,
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "1Hour": TimeFrame.Hour,
    "1Day":  TimeFrame.Day,
}

# Keep bars fresh enough for 1H strategy, but stop hammering Alpaca.
BAR_CACHE_TTL_SEC = 90.0
MIN_CALL_GAP_SEC = 0.35
MAX_RETRIES = 4


class DataFeed:
    def __init__(self):
        self.client = StockHistoricalDataClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
        )
        self._bar_cache: dict[str, tuple[float, pd.DataFrame]] = {}
        self._last_call_time = 0.0
        logger.info("DataFeed initialized -- connected to Alpaca Data API.")

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call_time
        if elapsed < MIN_CALL_GAP_SEC:
            time.sleep(MIN_CALL_GAP_SEC - elapsed)
        self._last_call_time = time.time()

    @staticmethod
    def _is_rate_limit(exc: Exception) -> bool:
        if isinstance(exc, APIError):
            msg = str(exc).lower()
            if "too many requests" in msg or "429" in msg:
                return True
            code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            if code == 429:
                return True
        text = str(exc).lower()
        return "too many requests" in text or "429" in text

    def get_historical_bars(self, symbol: str) -> pd.DataFrame | None:
        now_ts = time.time()
        cached = self._bar_cache.get(symbol)
        if cached is not None:
            cache_time, cached_df = cached
            if now_ts - cache_time < BAR_CACHE_TTL_SEC:
                return cached_df.copy()

        try:
            timeframe = TIMEFRAME_MAP.get(config.TIMEFRAME, TimeFrame.Hour)

            if timeframe == TimeFrame.Day:
                calendar_days = int(config.LOOKBACK_BARS * 1.6)
            elif timeframe == TimeFrame.Hour:
                calendar_days = int(config.LOOKBACK_BARS / 6.5 * 2.0)
            else:
                calendar_days = int(config.LOOKBACK_BARS / (6.5 * 60) * 2.0) + 10

            start = datetime.now() - timedelta(days=max(calendar_days, 30))

            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=timeframe,
                start=start,
            )

            bars = None
            last_err = None
            for attempt in range(MAX_RETRIES):
                self._throttle()
                try:
                    bars = self.client.get_stock_bars(request)
                    break
                except Exception as e:
                    last_err = e
                    if self._is_rate_limit(e) and attempt < MAX_RETRIES - 1:
                        wait = min(8.0, 1.0 * (2 ** attempt))
                        logger.warning(
                            f"Alpaca rate limit for {symbol}; retry in {wait:.1f}s "
                            f"(attempt {attempt + 1}/{MAX_RETRIES})"
                        )
                        time.sleep(wait)
                        continue
                    raise

            if bars is None:
                raise last_err or RuntimeError(f"No bars for {symbol}")

            df = bars.df

            if df.empty:
                logger.warning(f"No bar data returned for {symbol}.")
                return None

            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(symbol, level="symbol")

            df = df.tail(config.LOOKBACK_BARS)
            self._bar_cache[symbol] = (time.time(), df.copy())

            logger.info(
                f"Fetched {len(df)} bars for {symbol} "
                f"({config.TIMEFRAME}, {df.index[0]} -> {df.index[-1]})."
            )
            return df

        except Exception as e:
            logger.error(f"Failed to fetch bars for {symbol}: {e}", exc_info=True)
            if cached is not None:
                logger.warning(f"Serving stale cached bars for {symbol}.")
                return cached[1].copy()
            return None

    def get_latest_quote(self, symbol: str) -> dict | None:
        try:
            self._throttle()
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quotes = self.client.get_stock_latest_quote(request)

            quote = quotes[symbol]

            quote_data = {
                "bid_price": float(quote.bid_price),
                "ask_price": float(quote.ask_price),
                "bid_size":  quote.bid_size,
                "ask_size":  quote.ask_size,
            }

            logger.debug(
                f"Latest quote for {symbol}: "
                f"Bid=${quote_data['bid_price']:.2f} x {quote_data['bid_size']} | "
                f"Ask=${quote_data['ask_price']:.2f} x {quote_data['ask_size']}"
            )
            return quote_data

        except Exception as e:
            logger.error(f"Failed to fetch quote for {symbol}: {e}", exc_info=True)
            return None
