"""
bot_state.py — Shared in-process state for bot loops + dashboard
================================================================
Thread-safe signal cache, health timestamps, and India SOD equity.
"""

from __future__ import annotations

import threading
import time
from datetime import date
from typing import Any

_lock = threading.Lock()

_signals: dict[str, dict[str, Any]] = {}  # market -> {symbol: payload}
_health: dict[str, Any] = {
    "us_last_cycle": None,
    "india_last_cycle": None,
    "us_last_error": None,
    "india_last_error": None,
    "alpaca_429_count": 0,
    "started_at": time.time(),
}
_india_sod: dict[str, Any] = {"date": None, "equity": None}


def publish_signals(market: str, items: list[dict]) -> None:
    """items: [{symbol, signal, price, rsi, reason, ...}]"""
    key = market.upper()
    by_sym = {str(i["symbol"]): i for i in items if i.get("symbol")}
    with _lock:
        _signals[key] = {
            "updated_at": time.time(),
            "items": by_sym,
            "list": list(by_sym.values()),
        }


def get_signals(market: str, max_age_sec: float = 600.0) -> list[dict] | None:
    key = market.upper()
    with _lock:
        blob = _signals.get(key)
        if not blob:
            return None
        if time.time() - blob["updated_at"] > max_age_sec:
            return None
        return list(blob["list"])


def mark_cycle(market: str, error: str | None = None) -> None:
    key = "us" if market.upper() == "US" else "india"
    with _lock:
        _health[f"{key}_last_cycle"] = time.time()
        if error:
            _health[f"{key}_last_error"] = error
        elif error is None and f"{key}_last_error" in _health:
            # clear only when explicitly healthy
            pass


def mark_healthy(market: str) -> None:
    key = "us" if market.upper() == "US" else "india"
    with _lock:
        _health[f"{key}_last_cycle"] = time.time()
        _health[f"{key}_last_error"] = None


def note_alpaca_429() -> None:
    with _lock:
        _health["alpaca_429_count"] = int(_health.get("alpaca_429_count") or 0) + 1


def get_health() -> dict:
    with _lock:
        h = dict(_health)
        now = time.time()
        us_age = (now - h["us_last_cycle"]) if h.get("us_last_cycle") else None
        in_age = (now - h["india_last_cycle"]) if h.get("india_last_cycle") else None
        h["us_cycle_age_sec"] = round(us_age, 1) if us_age is not None else None
        h["india_cycle_age_sec"] = round(in_age, 1) if in_age is not None else None
        h["uptime_sec"] = round(now - h.get("started_at", now), 1)
        return h


def india_sod_equity(current_equity: float) -> float:
    """Return start-of-day equity for India (sticky per calendar day)."""
    today = date.today().isoformat()
    with _lock:
        if _india_sod.get("date") != today or _india_sod.get("equity") is None:
            _india_sod["date"] = today
            _india_sod["equity"] = float(current_equity)
        return float(_india_sod["equity"])
