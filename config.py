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


def _env_bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes")


def _env_float(key: str, default: str) -> float:
    return float(os.getenv(key, default))


def _env_int(key: str, default: str) -> int:
    return int(os.getenv(key, default))


# ===========================================================================
# Live Trading Safety Gate (India real money ONLY)
# ===========================================================================
# Real Angel One CNC orders ONLY when BOTH are set:
#   LIVE_TRADING=true
#   LIVE_CONFIRM=YES_REAL_MONEY
LIVE_TRADING: bool = _env_bool("LIVE_TRADING", "false")
LIVE_CONFIRM: str = os.getenv("LIVE_CONFIRM", "").strip()
LIVE_CONFIRMED: bool = LIVE_TRADING and LIVE_CONFIRM == "YES_REAL_MONEY"

TEST_MODE: bool = False

# ===========================================================================
# Market Toggles — both ON for 24/7 dual testing
# ===========================================================================
US_ENABLED: bool = _env_bool("US_ENABLED", "true")
# India paper sim uses LIVE Angel One quotes/candles but places NO real orders.
# Forced OFF automatically when LIVE_CONFIRMED (real money).
_INDIA_PAPER_ENV: bool = _env_bool("INDIA_PAPER", "true")
INDIA_PAPER: bool = _INDIA_PAPER_ENV and not LIVE_CONFIRMED

INDIA_PAPER_STARTING_CASH: float = _env_float("INDIA_PAPER_STARTING_CASH", "100000")

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
PAPER_TRADING: bool = _env_bool("ALPACA_PAPER", "true")

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

# Simple sector clusters — avoid piling into the same theme
US_CORRELATION_CLUSTERS: dict[str, list[str]] = {
    "us_tech": ["AAPL", "MSFT", "GOOGL", "NVDA", "AMZN", "META", "TSLA", "QQQ"],
    "us_finance": ["JPM", "V"],
    "us_index": ["SPY"],
    "us_health": ["LLY"],
}

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

INDIA_CORRELATION_CLUSTERS: dict[str, list[str]] = {
    "in_it": ["TCS", "INFY", "WIPRO"],
    "in_banks": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK"],
    "in_energy": ["RELIANCE"],
    "in_fmcg": ["HINDUNILVR", "ITC"],
    "in_infra": ["LT", "BHARTIARTL"],
}

# ===========================================================================
# Strategy Selection
#   trend_pullback  — PRIMARY (default): trend filter + pullback entry
#   mean_reversion  — SECONDARY: BB+RSI only in ranging markets (low ADX)
#   relative_strength — optional RS filter layered on primary/secondary
# ===========================================================================
STRATEGY_NAME: str = os.getenv("STRATEGY_NAME", "trend_pullback").strip().lower()
USE_RELATIVE_STRENGTH: bool = _env_bool("USE_RELATIVE_STRENGTH", "false")
RS_TOP_N: int = _env_int("RS_TOP_N", "5")
RS_LOOKBACK_BARS: int = _env_int("RS_LOOKBACK_BARS", "60")  # ~multi-week on 1H

TIMEFRAME: str = os.getenv("TIMEFRAME", "1Hour")
LOOKBACK_BARS: int = _env_int("LOOKBACK_BARS", "250")

# Shared indicator defaults (overridden per-market below)
SMA_SLOW: int = _env_int("SMA_SLOW", "200")
SMA_FAST: int = _env_int("SMA_FAST", "20")
EMA_PULLBACK: int = _env_int("EMA_PULLBACK", "21")
RSI_PERIOD: int = _env_int("RSI_PERIOD", "14")
RSI_BUY_THRESHOLD: float = _env_float("RSI_BUY_THRESHOLD", "35.0")
RSI_SELL_THRESHOLD: float = _env_float("RSI_SELL_THRESHOLD", "65.0")
BB_STD_DEV: float = _env_float("BB_STD_DEV", "2.0")
ATR_PERIOD: int = _env_int("ATR_PERIOD", "14")
ADX_PERIOD: int = _env_int("ADX_PERIOD", "14")
ADX_RANGE_MAX: float = _env_float("ADX_RANGE_MAX", "25.0")  # ranging if ADX below
VOLUME_AVG_PERIOD: int = _env_int("VOLUME_AVG_PERIOD", "20")
CONFIRM_BARS: int = _env_int("CONFIRM_BARS", "2")  # require N bars of signal

STRICT_SELL: bool = _env_bool("STRICT_SELL", "true")

# Per-market strategy params (US)
US_SMA_SLOW: int = _env_int("US_SMA_SLOW", str(SMA_SLOW))
US_SMA_FAST: int = _env_int("US_SMA_FAST", str(SMA_FAST))
US_EMA_PULLBACK: int = _env_int("US_EMA_PULLBACK", str(EMA_PULLBACK))
US_RSI_PERIOD: int = _env_int("US_RSI_PERIOD", str(RSI_PERIOD))
US_RSI_BUY: float = _env_float("US_RSI_BUY", str(RSI_BUY_THRESHOLD))
US_RSI_SELL: float = _env_float("US_RSI_SELL", str(RSI_SELL_THRESHOLD))
US_BB_STD: float = _env_float("US_BB_STD", str(BB_STD_DEV))
US_ADX_RANGE_MAX: float = _env_float("US_ADX_RANGE_MAX", str(ADX_RANGE_MAX))

# Per-market strategy params (India)
INDIA_SMA_SLOW: int = _env_int("INDIA_SMA_SLOW", str(SMA_SLOW))
INDIA_SMA_FAST: int = _env_int("INDIA_SMA_FAST", str(SMA_FAST))
INDIA_EMA_PULLBACK: int = _env_int("INDIA_EMA_PULLBACK", str(EMA_PULLBACK))
INDIA_RSI_PERIOD: int = _env_int("INDIA_RSI_PERIOD", str(RSI_PERIOD))
INDIA_RSI_BUY: float = _env_float("INDIA_RSI_BUY", str(RSI_BUY_THRESHOLD))
INDIA_RSI_SELL: float = _env_float("INDIA_RSI_SELL", str(RSI_SELL_THRESHOLD))
INDIA_BB_STD: float = _env_float("INDIA_BB_STD", str(BB_STD_DEV))
INDIA_ADX_RANGE_MAX: float = _env_float("INDIA_ADX_RANGE_MAX", str(ADX_RANGE_MAX))

# ===========================================================================
# Risk Parameters — size by risk-to-stop, not only % of equity
# ===========================================================================
RISK_PER_TRADE: float = _env_float("RISK_PER_TRADE", "0.0075")  # 0.75% equity
MAX_POSITION_PCT: float = _env_float("MAX_POSITION_PCT", "0.05")  # hard cap
ATR_STOP_MULT: float = _env_float("ATR_STOP_MULT", "2.0")
ATR_TRAIL_MULT: float = _env_float("ATR_TRAIL_MULT", "2.0")
TAKE_PROFIT_R: float = _env_float("TAKE_PROFIT_R", "2.5")  # 2.5R target
# Legacy pct stops kept as fallback when ATR unavailable
STOP_LOSS_PCT: float = _env_float("STOP_LOSS_PCT", "0.02")
TAKE_PROFIT_PCT: float = _env_float("TAKE_PROFIT_PCT", "0.04")
DAILY_DRAWDOWN_LIMIT: float = _env_float("DAILY_DRAWDOWN_LIMIT", "0.03")
MAX_SHARES_PER_ORDER: int = _env_int("MAX_SHARES_PER_ORDER", "100")
MAX_OPEN_POSITIONS: int = _env_int("MAX_OPEN_POSITIONS", "4")
MAX_CLUSTER_POSITIONS: int = _env_int("MAX_CLUSTER_POSITIONS", "2")

# Avoid first/last N minutes of the session (noise / poor fills)
AVOID_OPEN_MINUTES: int = _env_int("AVOID_OPEN_MINUTES", "15")
AVOID_CLOSE_MINUTES: int = _env_int("AVOID_CLOSE_MINUTES", "15")
ALLOW_OPEN_CLOSE_WINDOW: bool = _env_bool("ALLOW_OPEN_CLOSE_WINDOW", "false")

# Entry style: limit by default; market only if explicitly enabled
ALLOW_MARKET_ENTRIES: bool = _env_bool("ALLOW_MARKET_ENTRIES", "false")

# US limit fill timeout → cancel / requote
LIMIT_FILL_TIMEOUT_SEC: int = _env_int("LIMIT_FILL_TIMEOUT_SEC", "120")
LIMIT_REQUOTE_MAX: int = _env_int("LIMIT_REQUOTE_MAX", "2")

# ===========================================================================
# Trade Journal
# ===========================================================================
TRADE_JOURNAL_PATH: str = os.getenv("TRADE_JOURNAL_PATH", "trade_journal.db").strip()

# ===========================================================================
# Loop Intervals (bot process runs 24/7; trades only in market hours)
# ===========================================================================
LOOP_INTERVAL_SEC: int = _env_int("LOOP_INTERVAL_SEC", "300")
INDIA_LOOP_INTERVAL_SEC: int = _env_int("INDIA_LOOP_INTERVAL_SEC", "300")
