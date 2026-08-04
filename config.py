"""
config.py — Central Configuration Module
==========================================
India-only bot:
  India → Dhan (default) or Angel One — paper sim or live INR
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
# Real CNC orders ONLY when BOTH are set:
#   LIVE_TRADING=true
#   LIVE_CONFIRM=YES_REAL_MONEY
LIVE_TRADING: bool = _env_bool("LIVE_TRADING", "false")
LIVE_CONFIRM: str = os.getenv("LIVE_CONFIRM", "").strip()
LIVE_CONFIRMED: bool = LIVE_TRADING and LIVE_CONFIRM == "YES_REAL_MONEY"

TEST_MODE: bool = False

# ===========================================================================
# Market Toggles
# ===========================================================================
# India paper sim uses LIVE broker quotes/candles but places NO real orders.
# Forced OFF automatically when LIVE_CONFIRMED (real money).
_INDIA_PAPER_ENV: bool = _env_bool("INDIA_PAPER", "true")
INDIA_PAPER: bool = _INDIA_PAPER_ENV and not LIVE_CONFIRMED

INDIA_PAPER_STARTING_CASH: float = _env_float("INDIA_PAPER_STARTING_CASH", "100000")



# ===========================================================================
# India Market — Dhan (preferred) or Angel One
# ===========================================================================
# Broker selector: "dhan" | "angel"
# If unset: prefer dhan when Dhan client id is present, else angel.
_INDIA_BROKER_ENV: str = os.getenv("INDIA_BROKER", "").strip().lower()

DHAN_CLIENT_ID: str = os.getenv("DHAN_CLIENT_ID", "").strip()
DHAN_ACCESS_TOKEN: str = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
DHAN_PIN: str = os.getenv("DHAN_PIN", "").strip()
DHAN_TOTP_SECRET: str = os.getenv("DHAN_TOTP_SECRET", "").strip()
DHAN_API_KEY: str = os.getenv("DHAN_API_KEY", "").strip()
DHAN_API_SECRET: str = os.getenv("DHAN_API_SECRET", "").strip()

DHAN_CONFIGURED: bool = bool(
    DHAN_CLIENT_ID
    and (
        DHAN_ACCESS_TOKEN
        or (DHAN_PIN and DHAN_TOTP_SECRET)
    )
)

ANGEL_API_KEY: str = os.getenv("ANGEL_API_KEY", "").strip()
ANGEL_CLIENT_ID: str = os.getenv("ANGEL_CLIENT_ID", "").strip()
ANGEL_PIN: str = os.getenv("ANGEL_PIN", "").strip()
ANGEL_TOTP_SECRET: str = os.getenv("ANGEL_TOTP_SECRET", "").strip()

ANGEL_CONFIGURED: bool = bool(
    ANGEL_API_KEY and ANGEL_CLIENT_ID and ANGEL_PIN and ANGEL_TOTP_SECRET
)

if _INDIA_BROKER_ENV in ("dhan", "angel"):
    INDIA_BROKER: str = _INDIA_BROKER_ENV
elif DHAN_CONFIGURED:
    INDIA_BROKER = "dhan"
elif ANGEL_CONFIGURED:
    INDIA_BROKER = "angel"
else:
    INDIA_BROKER = "dhan"

INDIA_ENABLED: bool = (
    (INDIA_BROKER == "dhan" and DHAN_CONFIGURED)
    or (INDIA_BROKER == "angel" and ANGEL_CONFIGURED)
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
#   trend_pullback   — PRIMARY: trend filter + pullback entry
#   mean_reversion   — BB+RSI only in ranging markets (low ADX)
#   regime_adaptive  — ADX switches between trend_pullback and mean_reversion
#   breakout         — Donchian-style high breakout with volume
#   + USE_RELATIVE_STRENGTH — optional RS top-N gate on BUY
# ===========================================================================
STRATEGY_NAME: str = os.getenv("STRATEGY_NAME", "trend_pullback").strip().lower()
USE_RELATIVE_STRENGTH: bool = _env_bool("USE_RELATIVE_STRENGTH", "true")
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



# Sync software trailing stops onto broker stop orders
SYNC_BROKER_STOPS: bool = _env_bool("SYNC_BROKER_STOPS", "true")

# Multi-timeframe: require daily close > SMA200 for 1H buys
USE_MTF_FILTER: bool = _env_bool("USE_MTF_FILTER", "true")
# Index regime: only buy stocks when NIFTY proxy is in uptrend
USE_REGIME_FILTER: bool = _env_bool("USE_REGIME_FILTER", "true")
REGIME_SYMBOL_INDIA: str = os.getenv("REGIME_SYMBOL_INDIA", "RELIANCE").strip().upper()

# Backtest realism
BT_COMMISSION_PCT: float = _env_float("BT_COMMISSION_PCT", "0.001")  # 0.1% round-trip approx
BT_SLIPPAGE_PCT: float = _env_float("BT_SLIPPAGE_PCT", "0.0005")  # 5 bps per side

# Alerts (optional)
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "").strip()
ALERT_WEBHOOK_URL: str = os.getenv("ALERT_WEBHOOK_URL", "").strip()

# ===========================================================================
# Trade Journal
# ===========================================================================
TRADE_JOURNAL_PATH: str = os.getenv("TRADE_JOURNAL_PATH", "trade_journal.db").strip()

# ===========================================================================
# Loop Intervals (bot process runs 24/7; trades only in market hours)
# ===========================================================================

INDIA_LOOP_INTERVAL_SEC: int = _env_int("INDIA_LOOP_INTERVAL_SEC", "300")
