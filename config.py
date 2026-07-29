"""
config.py — Central Configuration Module
==========================================
Stores all configurable parameters for the trading bot.
Loads API credentials securely from .env file using python-dotenv.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ===========================================================================
# US Market — Alpaca Paper Trading API Credentials
# ===========================================================================
ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "").strip()
ALPACA_SECRET_KEY: str = os.getenv("ALPACA_SECRET_KEY", "").strip()
BASE_URL: str = os.getenv("BASE_URL", "https://paper-api.alpaca.markets").strip()

IS_PLACEHOLDER_KEY: bool = (
    not ALPACA_API_KEY 
    or "your_api_key_here" in ALPACA_API_KEY 
    or "your_copied_api_key" in ALPACA_API_KEY
)

PAPER_TRADING: bool = True
TEST_MODE: bool = False

# ---------------------------------------------------------------------------
# US Stock Universe — Top Liquid Large-Cap Stocks & ETFs
# ---------------------------------------------------------------------------
STOCK_UNIVERSE: list[str] = [
    "SPY",    # S&P 500 ETF
    "QQQ",    # Nasdaq 100 ETF
    "AAPL",   # Apple
    "MSFT",   # Microsoft
    "GOOGL",  # Google / Alphabet
    "NVDA",   # Nvidia
    "AMZN",   # Amazon
    "META",   # Meta / Facebook
    "TSLA",   # Tesla
    "JPM",    # JPMorgan Chase
    "V",      # Visa
    "LLY",    # Eli Lilly
]

# ===========================================================================
# India Market — Angel One SmartAPI Credentials
# ===========================================================================
ANGEL_API_KEY: str = os.getenv("ANGEL_API_KEY", "").strip()
ANGEL_CLIENT_ID: str = os.getenv("ANGEL_CLIENT_ID", "").strip()
ANGEL_PIN: str = os.getenv("ANGEL_PIN", "").strip()
ANGEL_TOTP_SECRET: str = os.getenv("ANGEL_TOTP_SECRET", "").strip()

# Auto-detect if India trading is configured
INDIA_ENABLED: bool = bool(
    ANGEL_API_KEY and ANGEL_CLIENT_ID and ANGEL_PIN and ANGEL_TOTP_SECRET
)

# ---------------------------------------------------------------------------
# India Stock Universe — Top Nifty 50 Large-Cap Stocks (NSE)
# ---------------------------------------------------------------------------
INDIA_STOCK_UNIVERSE: list[str] = [
    "RELIANCE",    # Reliance Industries
    "TCS",         # Tata Consultancy Services
    "HDFCBANK",    # HDFC Bank
    "INFY",        # Infosys
    "ICICIBANK",   # ICICI Bank
    "HINDUNILVR",  # Hindustan Unilever
    "ITC",         # ITC Ltd.
    "SBIN",        # State Bank of India
    "BHARTIARTL",  # Bharti Airtel
    "LT",          # Larsen & Toubro
    "KOTAKBANK",   # Kotak Mahindra Bank
    "WIPRO",       # Wipro
]

# ===========================================================================
# Strategy Parameters (Shared for both US & India)
# ===========================================================================
TIMEFRAME: str = "1Hour"
LOOKBACK_BARS: int = 250

SMA_SLOW: int = 200
SMA_FAST: int = 20
RSI_PERIOD: int = 14

RSI_BUY_THRESHOLD: float = 35.0     # Buy when oversold dip < 35
RSI_SELL_THRESHOLD: float = 65.0    # Take profit when overbought > 65

BB_STD_DEV: float = 2.0

# ===========================================================================
# Risk Parameters (Shared for both US & India)
# ===========================================================================
MAX_POSITION_PCT: float = 0.05     # Max 5% of portfolio equity per stock
STOP_LOSS_PCT: float = 0.02       # 2% hard stop-loss
TAKE_PROFIT_PCT: float = 0.04     # 4% take-profit target
DAILY_DRAWDOWN_LIMIT: float = 0.03 # 3% daily drawdown kill-switch

# ===========================================================================
# Loop Intervals
# ===========================================================================
LOOP_INTERVAL_SEC: int = 300       # 5-minute main loop cadence (US)
INDIA_LOOP_INTERVAL_SEC: int = 300 # 5-minute main loop cadence (India)
