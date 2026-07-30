"""
config.py — Central Configuration Module
==========================================
Dual-market bot:
  US   → Alpaca PAPER (fake USD) + live US market data  [testing]
  India → Angel One PAPER SIM (fake INR) + live NSE data [testing]
          Real INR orders only when LIVE_TRADING is armed
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ===========================================================================
# Live Trading Safety Gate (India real money ONLY)
# ===========================================================================
# Real Angel One CNC orders ONLY when BOTH are set:
#   LIVE_TRADING=true
#   LIVE_CONFIRM=YES_REAL_MONEY
LIVE_TRADING: bool = os.getenv("LIVE_TRADING", "false").strip().lower() in (
    "1",
    "true",
    "yes",
)
LIVE_CONFIRM: str = os.getenv("LIVE_CONFIRM", "").strip()
LIVE_CONFIRMED: bool = LIVE_TRADING and LIVE_CONFIRM == "YES_REAL_MONEY"

TEST_MODE: bool = False

# ===========================================================================
# Market Toggles — both ON for 24/7 dual testing
# ===========================================================================
US_ENABLED: bool = os.getenv("US_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
# India paper sim uses LIVE Angel One quotes/candles but places NO real orders.
# Forced OFF automatically when LIVE_CONFIRMED (real money).
_INDIA_PAPER_ENV: bool = os.getenv("INDIA_PAPER", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
INDIA_PAPER: bool = _INDIA_PAPER_ENV and not LIVE_CONFIRMED

INDIA_PAPER_STARTING_CASH: float = float(
    os.getenv("INDIA_PAPER_STARTING_CASH", "100000")
)

# ===========================================================================
# US Market — Alpaca PAPER (default for testing)
# ===========================================================================
ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "").strip()
ALPACA_SECRET_KEY: str = os.getenv("ALPACA_SECRET_KEY", "").strip()
BASE_URL: str = os.getenv(
    "BASE_URL", "https://paper-api.alpaca.markets"
).strip()

IS_PLACEHOLDER_KEY: bool = (
    not ALPACA_API_KEY
    or "your_api_key_here" in ALPACA_API_KEY
    or "your_copied_api_key" in ALPACA_API_KEY
)

# Paper = fake USD on Alpaca (still uses LIVE market prices)
PAPER_TRADING: bool = os.getenv("ALPACA_PAPER", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)

STOCK_UNIVERSE: list[str] = [
    "SPY",
    "QQQ",
    "AAPL",
    "MSFT",
    "GOOGL",
    "NVDA",
    "AMZN",
    "META",
    "TSLA",
    "JPM",
    "V",
    "LLY",
]

# ===========================================================================
# India Market — Angel One (live data; paper sim or real orders)
# ===========================================================================
ANGEL_API_KEY: str = os.getenv("ANGEL_API_KEY", "").strip()
ANGEL_CLIENT_ID: str = os.getenv("ANGEL_CLIENT_ID", "").strip()
ANGEL_PIN: str = os.getenv("ANGEL_PIN", "").strip()
ANGEL_TOTP_SECRET: str = os.getenv("ANGEL_TOTP_SECRET", "").strip()

INDIA_ENABLED: bool = bool(
    ANGEL_API_KEY and ANGEL_CLIENT_ID and ANGEL_PIN and ANGEL_TOTP_SECRET
)

INDIA_STOCK_UNIVERSE: list[str] = [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ICICIBANK",
    "HINDUNILVR",
    "ITC",
    "SBIN",
    "BHARTIARTL",
    "LT",
    "KOTAKBANK",
    "WIPRO",
]

# ===========================================================================
# Strategy Parameters
# ===========================================================================
TIMEFRAME: str = "1Hour"
LOOKBACK_BARS: int = 250

SMA_SLOW: int = 200
SMA_FAST: int = 20
RSI_PERIOD: int = 14

RSI_BUY_THRESHOLD: float = 35.0
RSI_SELL_THRESHOLD: float = 65.0

BB_STD_DEV: float = 2.0

STRICT_SELL: bool = os.getenv("STRICT_SELL", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)

# ===========================================================================
# Risk Parameters
# ===========================================================================
MAX_POSITION_PCT: float = float(os.getenv("MAX_POSITION_PCT", "0.05"))
STOP_LOSS_PCT: float = float(os.getenv("STOP_LOSS_PCT", "0.02"))
TAKE_PROFIT_PCT: float = float(os.getenv("TAKE_PROFIT_PCT", "0.04"))
DAILY_DRAWDOWN_LIMIT: float = float(os.getenv("DAILY_DRAWDOWN_LIMIT", "0.03"))
MAX_SHARES_PER_ORDER: int = int(os.getenv("MAX_SHARES_PER_ORDER", "100"))

# ===========================================================================
# Loop Intervals (bot process runs 24/7; trades only in market hours)
# ===========================================================================
LOOP_INTERVAL_SEC: int = int(os.getenv("LOOP_INTERVAL_SEC", "300"))
INDIA_LOOP_INTERVAL_SEC: int = int(os.getenv("INDIA_LOOP_INTERVAL_SEC", "300"))
