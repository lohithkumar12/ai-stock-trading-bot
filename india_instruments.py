"""
india_instruments.py — NSE Instrument Token Mapping
=====================================================
Maps NSE stock symbols to numeric security IDs used by Dhan (security_id)
and Angel One (symboltoken). These IDs align for common NSE equities
(e.g. HDFCBANK=1333).
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Nifty 50 Large-Cap Stocks — Symbol Token Mapping
# ---------------------------------------------------------------------------
# Format: "DISPLAY_NAME": {"token": "...", "symbol": "SYMBOL-EQ", "exchange": "NSE"}
#
# These tokens are stable and rarely change. Verified against Angel One
# master instrument file.
# ---------------------------------------------------------------------------

INDIA_INSTRUMENTS: dict[str, dict] = {
    "RELIANCE": {
        "token": "2885",
        "symbol": "RELIANCE-EQ",
        "exchange": "NSE",
        "name": "Reliance Industries Ltd.",
    },
    "TCS": {
        "token": "11536",
        "symbol": "TCS-EQ",
        "exchange": "NSE",
        "name": "Tata Consultancy Services Ltd.",
    },
    "HDFCBANK": {
        "token": "1333",
        "symbol": "HDFCBANK-EQ",
        "exchange": "NSE",
        "name": "HDFC Bank Ltd.",
    },
    "INFY": {
        "token": "1594",
        "symbol": "INFY-EQ",
        "exchange": "NSE",
        "name": "Infosys Ltd.",
    },
    "ICICIBANK": {
        "token": "4963",
        "symbol": "ICICIBANK-EQ",
        "exchange": "NSE",
        "name": "ICICI Bank Ltd.",
    },
    "HINDUNILVR": {
        "token": "1394",
        "symbol": "HINDUNILVR-EQ",
        "exchange": "NSE",
        "name": "Hindustan Unilever Ltd.",
    },
    "ITC": {
        "token": "1660",
        "symbol": "ITC-EQ",
        "exchange": "NSE",
        "name": "ITC Ltd.",
    },
    "SBIN": {
        "token": "3045",
        "symbol": "SBIN-EQ",
        "exchange": "NSE",
        "name": "State Bank of India",
    },
    "BHARTIARTL": {
        "token": "10604",
        "symbol": "BHARTIARTL-EQ",
        "exchange": "NSE",
        "name": "Bharti Airtel Ltd.",
    },
    "LT": {
        "token": "11483",
        "symbol": "LT-EQ",
        "exchange": "NSE",
        "name": "Larsen & Toubro Ltd.",
    },
    "KOTAKBANK": {
        "token": "1922",
        "symbol": "KOTAKBANK-EQ",
        "exchange": "NSE",
        "name": "Kotak Mahindra Bank Ltd.",
    },
    "WIPRO": {
        "token": "3787",
        "symbol": "WIPRO-EQ",
        "exchange": "NSE",
        "name": "Wipro Ltd.",
    },
}


def get_token(symbol: str) -> str | None:
    """Get the Angel One symbol token for a given stock symbol."""
    info = INDIA_INSTRUMENTS.get(symbol)
    return info["token"] if info else None


def get_trading_symbol(symbol: str) -> str | None:
    """Get the full trading symbol (e.g., 'RELIANCE-EQ') for a given stock."""
    info = INDIA_INSTRUMENTS.get(symbol)
    return info["symbol"] if info else None


def get_exchange(symbol: str) -> str:
    """Get exchange for a given symbol. Defaults to NSE."""
    info = INDIA_INSTRUMENTS.get(symbol)
    return info["exchange"] if info else "NSE"


def get_all_symbols() -> list[str]:
    """Return list of all tracked India stock symbols."""
    return list(INDIA_INSTRUMENTS.keys())
