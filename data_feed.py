"""
data_feed.py — Market Data Feed Module
========================================
Fetches historical bar data and real-time quotes from Alpaca's Stock Data API.
Uses the official alpaca-py SDK's StockHistoricalDataClient.
"""

import logging
from datetime import datetime, timedelta

import pandas as pd
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


class DataFeed:
    def __init__(self):
        self.client = StockHistoricalDataClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
        )
        logger.info("DataFeed initialized -- connected to Alpaca Data API.")

    def get_historical_bars(self, symbol: str) -> pd.DataFrame | None:
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

            bars = self.client.get_stock_bars(request)
            df = bars.df

            if df.empty:
                logger.warning(f"No bar data returned for {symbol}.")
                return None

            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(symbol, level="symbol")

            df = df.tail(config.LOOKBACK_BARS)

            logger.info(
                f"Fetched {len(df)} bars for {symbol} "
                f"({config.TIMEFRAME}, {df.index[0]} -> {df.index[-1]})."
            )
            return df

        except Exception as e:
            logger.error(f"Failed to fetch bars for {symbol}: {e}", exc_info=True)
            return None

    def get_latest_quote(self, symbol: str) -> dict | None:
        try:
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
