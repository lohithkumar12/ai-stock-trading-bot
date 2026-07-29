"""
config.py — Central Configuration Module
==========================================
Stores all configurable parameters for the trading bot.
Loads API credentials securely from .env file using python-dotenv.
"""

import os
from dotenv import load_dotenv

load_dotenv()

ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "").strip()
ALPACA_SECRET_KEY: str = os.getenv("ALPACA_SECRET_KEY", "").strip()
BASE_URL: str = os.getenv("BASE_URL", "https://paper-api.alpaca.markets").strip()

IS_PLACEHOLDER_KEY: bool = (
    not ALPACA_API_KEY 
    or "your_api_key_here" in ALPACA_API_KEY 
    or "your_copied_api_key" in ALPACA_API_KEY
)

PAPER_TRADING: bool = True

# Production mode
TEST_MODE: bool = False

STOCK_UNIVERSE: list[str] = ["SPY", "QQQ", "AAPL", "MSFT", "GOOGL"]

TIMEFRAME: str = "1Hour"
LOOKBACK_BARS: int = 250

SMA_SLOW: int = 200
SMA_FAST: int = 20
RSI_PERIOD: int = 14

RSI_BUY_THRESHOLD: float = 35.0     # Production 35.0 threshold
RSI_SELL_THRESHOLD: float = 65.0

BB_STD_DEV: float = 2.0

MAX_POSITION_PCT: float = 0.05
STOP_LOSS_PCT: float = 0.02
TAKE_PROFIT_PCT: float = 0.04
DAILY_DRAWDOWN_LIMIT: float = 0.03

LOOP_INTERVAL_SEC: int = 300
