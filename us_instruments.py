"""
us_instruments.py — US Stock Instrument Mapping (Dhan Global Stocks)
=====================================================================
Maps US stock tickers to DhanHQ Global Stocks security IDs.

These security IDs are specific to Dhan's Global Stocks segment
(India INX / GIFT City). They differ from NSE/BSE IDs.

To add custom US symbols, look up the security_id from Dhan's
Global Stocks instrument CSV at:
  https://api.dhan.co/v2/instrument/GLOBAL
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default US Universe — Dhan Global Stocks Security IDs
# ---------------------------------------------------------------------------
# Format: "TICKER": {"security_id": "...", "name": "...", "exchange": "GLOBAL"}
#
# Security IDs sourced from Dhan Global Stocks instrument master.
# These map to India INX listed global depository receipts.
# ---------------------------------------------------------------------------

US_INSTRUMENTS: dict[str, dict] = {
    "AAPL": {
        "security_id": "19913",
        "name": "Apple Inc.",
        "exchange": "GLOBAL",
    },
    "MSFT": {
        "security_id": "19940",
        "name": "Microsoft Corporation",
        "exchange": "GLOBAL",
    },
    "GOOGL": {
        "security_id": "19923",
        "name": "Alphabet Inc. (Class A)",
        "exchange": "GLOBAL",
    },
    "AMZN": {
        "security_id": "19914",
        "name": "Amazon.com Inc.",
        "exchange": "GLOBAL",
    },
    "NVDA": {
        "security_id": "19941",
        "name": "NVIDIA Corporation",
        "exchange": "GLOBAL",
    },
    "META": {
        "security_id": "19937",
        "name": "Meta Platforms Inc.",
        "exchange": "GLOBAL",
    },
    "TSLA": {
        "security_id": "19960",
        "name": "Tesla Inc.",
        "exchange": "GLOBAL",
    },
    "JPM": {
        "security_id": "19929",
        "name": "JPMorgan Chase & Co.",
        "exchange": "GLOBAL",
    },
    "V": {
        "security_id": "19962",
        "name": "Visa Inc.",
        "exchange": "GLOBAL",
    },
    "UNH": {
        "security_id": "19961",
        "name": "UnitedHealth Group Inc.",
        "exchange": "GLOBAL",
    },
}


def get_us_security_id(symbol: str) -> str | None:
    """Get the Dhan Global Stocks security_id for a US ticker."""
    info = US_INSTRUMENTS.get(symbol.upper())
    return info["security_id"] if info else None


def get_us_exchange(symbol: str) -> str:
    """Get exchange segment for a US symbol. Always 'GLOBAL'."""
    return "GLOBAL"


def get_us_name(symbol: str) -> str:
    """Get human-readable company name."""
    info = US_INSTRUMENTS.get(symbol.upper())
    return info["name"] if info else symbol


def get_all_us_symbols() -> list[str]:
    """Return list of all tracked US stock symbols."""
    return list(US_INSTRUMENTS.keys())


def is_us_symbol(symbol: str) -> bool:
    """Check if a symbol is in the US instruments map."""
    return symbol.upper() in US_INSTRUMENTS
