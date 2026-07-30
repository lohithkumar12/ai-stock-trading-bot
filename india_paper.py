"""
india_paper.py — Virtual INR Portfolio (Angel One has no paper account)
=======================================================================
Uses LIVE Angel One candles + LTP for marks, but never places broker orders.
State persists in india_paper_portfolio.json so Render restarts keep history.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import config

logger = logging.getLogger(__name__)

PORTFOLIO_PATH = Path(__file__).resolve().parent / "india_paper_portfolio.json"
_lock = threading.Lock()


class IndiaPaperPortfolio:
    """Fake INR account marked to live NSE prices."""

    def __init__(self, starting_cash: float | None = None):
        self.starting_cash = (
            starting_cash
            if starting_cash is not None
            else config.INDIA_PAPER_STARTING_CASH
        )
        self.cash: float = self.starting_cash
        self.positions: dict[str, dict] = {}  # symbol -> {qty, avg_entry_price}
        self.realized_pl: float = 0.0
        self.start_of_day_equity: float | None = None
        self._load()

    def _load(self):
        if not PORTFOLIO_PATH.exists():
            self._save()
            logger.info(
                f"India PAPER portfolio created | Cash=Rs {self.cash:,.2f}"
            )
            return
        try:
            data = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
            self.cash = float(data.get("cash", self.starting_cash))
            self.positions = data.get("positions", {}) or {}
            self.realized_pl = float(data.get("realized_pl", 0))
            self.start_of_day_equity = data.get("start_of_day_equity")
            logger.info(
                f"India PAPER portfolio loaded | Cash=Rs {self.cash:,.2f} | "
                f"Positions={list(self.positions.keys())}"
            )
        except Exception as e:
            logger.error(f"Failed to load paper portfolio: {e}")

    def _save(self):
        payload = {
            "cash": self.cash,
            "positions": self.positions,
            "realized_pl": self.realized_pl,
            "start_of_day_equity": self.start_of_day_equity,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        PORTFOLIO_PATH.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def reset(self, starting_cash: float | None = None):
        with _lock:
            self.cash = starting_cash if starting_cash is not None else self.starting_cash
            self.positions = {}
            self.realized_pl = 0.0
            self.start_of_day_equity = None
            self._save()
            logger.warning(f"India PAPER portfolio RESET | Cash=Rs {self.cash:,.2f}")

    def get_account_info(self, mark_prices: dict[str, float] | None = None) -> dict:
        marks = mark_prices or {}
        equity = self.cash
        for symbol, pos in self.positions.items():
            px = float(marks.get(symbol, pos.get("avg_entry_price", 0)))
            equity += pos["qty"] * px

        if self.start_of_day_equity is None:
            self.start_of_day_equity = equity
            self._save()

        return {
            "equity": round(equity, 2),
            "available_cash": round(self.cash, 2),
            "used_margin": 0.0,
            "net": round(equity, 2),
            "last_equity": round(self.start_of_day_equity, 2),
            "paper": True,
        }

    def get_open_positions(self, mark_prices: dict[str, float] | None = None) -> dict:
        marks = mark_prices or {}
        out = {}
        for symbol, pos in self.positions.items():
            qty = int(pos["qty"])
            entry = float(pos["avg_entry_price"])
            ltp = float(marks.get(symbol, entry))
            pnl = (ltp - entry) * qty
            pnl_pct = ((ltp - entry) / entry) if entry > 0 else 0.0
            out[symbol] = {
                "qty": qty,
                "avg_entry_price": entry,
                "current_price": ltp,
                "market_value": qty * ltp,
                "unrealized_pl": pnl,
                "unrealized_plpc": pnl_pct,
                "trading_symbol": f"{symbol}-EQ",
                "token": "",
                "source": "paper",
            }
        return out

    def buy(self, symbol: str, qty: int, price: float) -> str | None:
        if qty <= 0 or price <= 0:
            return None
        cost = qty * price
        with _lock:
            if cost > self.cash:
                logger.warning(
                    f"[PAPER] BUY blocked {symbol}: need Rs {cost:,.2f}, "
                    f"have Rs {self.cash:,.2f}"
                )
                return None

            self.cash -= cost
            if symbol in self.positions:
                old = self.positions[symbol]
                new_qty = old["qty"] + qty
                new_avg = ((old["avg_entry_price"] * old["qty"]) + cost) / new_qty
                self.positions[symbol] = {
                    "qty": new_qty,
                    "avg_entry_price": round(new_avg, 4),
                }
            else:
                self.positions[symbol] = {
                    "qty": qty,
                    "avg_entry_price": round(price, 4),
                }

            order_id = f"PAPER-{uuid.uuid4().hex[:10].upper()}"
            self._save()
            logger.warning(
                f"[PAPER BUY] {symbol} | Qty={qty} | Price={price:.2f} | "
                f"Cash left=Rs {self.cash:,.2f} | ID={order_id}"
            )
            return order_id

    def sell(self, symbol: str, qty: int, price: float) -> str | None:
        if qty <= 0 or price <= 0:
            return None
        with _lock:
            if symbol not in self.positions:
                logger.warning(f"[PAPER] SELL blocked — no position in {symbol}")
                return None

            held = self.positions[symbol]["qty"]
            if qty > held:
                qty = held

            entry = self.positions[symbol]["avg_entry_price"]
            proceeds = qty * price
            self.realized_pl += (price - entry) * qty
            self.cash += proceeds

            remaining = held - qty
            if remaining <= 0:
                del self.positions[symbol]
            else:
                self.positions[symbol]["qty"] = remaining

            order_id = f"PAPER-{uuid.uuid4().hex[:10].upper()}"
            self._save()
            logger.warning(
                f"[PAPER SELL] {symbol} | Qty={qty} | Price={price:.2f} | "
                f"Cash=Rs {self.cash:,.2f} | ID={order_id}"
            )
            return order_id

    def reset_day_equity(self, equity: float):
        self.start_of_day_equity = equity
        self._save()
