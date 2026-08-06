"""
us_instruments.py — US Stock Instrument Mapping (Dhan Global Stocks)
=====================================================================
Maps US stock tickers to DhanHQ Global Stocks security IDs (SCRIP_CODE).

Official instrument master:
  https://api-global-stocks.dhan.co/api-data/us-stock-scrip-master.csv

Security IDs differ from NSE/BSE. Prefer runtime refresh from the CSV;
static US_INSTRUMENTS is a seed for offline / first boot.
"""

from __future__ import annotations

import csv
import io
import logging
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)

US_SCRIP_MASTER_URL = (
    "https://api-global-stocks.dhan.co/api-data/us-stock-scrip-master.csv"
)
CACHE_TTL_SEC = 6 * 3600  # 6 hours

# ---------------------------------------------------------------------------
# Default US Universe — SCRIP_CODE from official Global Stocks master
# ---------------------------------------------------------------------------
US_INSTRUMENTS: dict[str, dict] = {
    "AAPL": {
        "security_id": "10000025",
        "name": "Apple Inc.",
        "exchange": "GLOBAL",
    },
    "MSFT": {
        "security_id": "10006754",
        "name": "Microsoft Corporation",
        "exchange": "GLOBAL",
    },
    "GOOGL": {
        "security_id": "10004393",
        "name": "Alphabet Inc. (Class A)",
        "exchange": "GLOBAL",
    },
    "AMZN": {
        "security_id": "10000496",
        "name": "Amazon.com Inc.",
        "exchange": "GLOBAL",
    },
    "NVDA": {
        "security_id": "10007290",
        "name": "NVIDIA Corporation",
        "exchange": "GLOBAL",
    },
    "META": {
        "security_id": "10006471",
        "name": "Meta Platforms Inc.",
        "exchange": "GLOBAL",
    },
    "TSLA": {
        "security_id": "10010311",
        "name": "Tesla Inc.",
        "exchange": "GLOBAL",
    },
    "JPM": {
        "security_id": "10005648",
        "name": "JPMorgan Chase & Co.",
        "exchange": "GLOBAL",
    },
    "V": {
        "security_id": "10010679",
        "name": "Visa Inc.",
        "exchange": "GLOBAL",
    },
    "UNH": {
        "security_id": "10010532",
        "name": "UnitedHealth Group Inc.",
        "exchange": "GLOBAL",
    },
}

_master_lock = threading.Lock()
_master_by_symbol: dict[str, dict] = {}
_last_download_time = 0.0
_master_row_count = 0


def load_us_scrip_master(force_download: bool = False) -> bool:
    """Download and index the official US Global Stocks scrip master CSV."""
    global _last_download_time, _master_by_symbol, _master_row_count
    with _master_lock:
        now = time.time()
        if (
            not force_download
            and _master_by_symbol
            and (now - _last_download_time < CACHE_TTL_SEC)
        ):
            return True

        try:
            logger.info(f"[US] Fetching Global Stocks scrip master from {US_SCRIP_MASTER_URL}...")
            req = urllib.request.Request(
                US_SCRIP_MASTER_URL,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                content = resp.read().decode("utf-8", errors="ignore")

            reader = csv.DictReader(io.StringIO(content))
            by_symbol: dict[str, dict] = {}
            count = 0
            for row in reader:
                count += 1
                sym = (
                    (row.get("SYMBOL") or row.get("EXCH_SYMBOL") or row.get("TRADING_SYMBOL") or "")
                    .strip()
                    .upper()
                )
                sec_id = str(row.get("SCRIP_CODE") or "").strip()
                if not sym or not sec_id:
                    continue
                name = (
                    row.get("CUSTOM_SYMBOL")
                    or row.get("SYMBOL_NAME")
                    or sym
                ).strip()
                exch = (row.get("CUSTOM_EXCH") or row.get("EXCHANGE") or "GLOBAL").strip()
                by_symbol[sym] = {
                    "security_id": sec_id,
                    "name": name,
                    "exchange": "GLOBAL",
                    "custom_exch": exch,
                    "resolved_from_master": True,
                }

            if by_symbol:
                _master_by_symbol = by_symbol
                _master_row_count = count
                _last_download_time = now
                # Align static seed map with fresh SCRIP_CODEs
                for ticker, info in US_INSTRUMENTS.items():
                    master = by_symbol.get(ticker)
                    if master and master.get("security_id"):
                        info["security_id"] = str(master["security_id"])
                        if master.get("name"):
                            info["name"] = master["name"]
                logger.info(
                    f"[US] Loaded Global scrip master: {count} rows | "
                    f"symbols={len(by_symbol)}"
                )
                return True

            logger.warning("[US] Global scrip master download returned no symbols")
            return False
        except Exception as e:
            logger.warning(f"[US] Global scrip master fetch failed: {e}")
            return bool(_master_by_symbol)


def master_status() -> dict:
    with _master_lock:
        age = (
            round(time.time() - _last_download_time, 1)
            if _last_download_time > 0
            else None
        )
        return {
            "loaded": bool(_master_by_symbol),
            "symbol_count": len(_master_by_symbol),
            "row_count": _master_row_count,
            "age_sec": age,
            "url": US_SCRIP_MASTER_URL,
        }


def resolve_us_instrument(symbol: str) -> dict | None:
    """Resolve ticker → security_id (master preferred, then static seed)."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    with _master_lock:
        hit = _master_by_symbol.get(sym)
        if hit:
            return dict(hit)
    seed = US_INSTRUMENTS.get(sym)
    if seed:
        return {
            "security_id": str(seed["security_id"]),
            "name": seed.get("name", sym),
            "exchange": seed.get("exchange", "GLOBAL"),
            "resolved_from_master": False,
        }
    return None


def get_us_security_id(symbol: str) -> str | None:
    """Get the Dhan Global Stocks security_id (SCRIP_CODE) for a US ticker."""
    info = resolve_us_instrument(symbol)
    if not info:
        return None
    sec = str(info.get("security_id") or "").strip()
    return sec or None


def get_us_exchange(symbol: str) -> str:
    """Get exchange segment for a US symbol. Always 'GLOBAL'."""
    return "GLOBAL"


def get_us_name(symbol: str) -> str:
    """Get human-readable company name."""
    info = resolve_us_instrument(symbol)
    if info and info.get("name"):
        return str(info["name"])
    return symbol


def get_all_us_symbols() -> list[str]:
    """Return list of all tracked US stock symbols (static universe seed)."""
    return list(US_INSTRUMENTS.keys())


def is_us_symbol(symbol: str) -> bool:
    """Check if a symbol is in the US instruments map or loaded master."""
    sym = (symbol or "").strip().upper()
    if sym in US_INSTRUMENTS:
        return True
    with _master_lock:
        return sym in _master_by_symbol
