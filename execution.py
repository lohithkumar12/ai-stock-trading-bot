"""
execution.py — Trade Execution Module
========================================
Handles order submission and position management via Alpaca's Trading API.

Key Principles:
  - NEVER uses market orders for entries unless ALLOW_MARKET_ENTRIES.
  - All entries are Bracket Orders (Limit Entry + Stop-Loss + Take-Profit).
  - Limit fill timeout → cancel / requote up to LIMIT_REQUOTE_MAX times.
"""

from __future__ import annotations

import logging
import time

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    LimitOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

import config

logger = logging.getLogger(__name__)


class TradeExecutor:
    def __init__(self):
        self.client = TradingClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
            paper=config.PAPER_TRADING,
        )
        mode = "PAPER" if config.PAPER_TRADING else "LIVE"
        # Track pending limit entries for timeout/requote: order_id -> meta
        self._pending_limits: dict[str, dict] = {}
        logger.info(f"TradeExecutor initialized — Mode: {mode}")

    def get_account_info(self) -> dict | None:
        try:
            account = self.client.get_account()
            info = {
                "equity": float(account.equity),
                "buying_power": float(account.buying_power),
                "last_equity": float(account.last_equity),
                "cash": float(account.cash),
                "portfolio_value": float(account.portfolio_value),
            }
            logger.info(
                f"Account | Equity=${info['equity']:,.2f} | "
                f"Buying Power=${info['buying_power']:,.2f} | "
                f"Cash=${info['cash']:,.2f}"
            )
            return info
        except Exception as e:
            logger.error(f"Failed to fetch account info: {e}", exc_info=True)
            return None

    def get_open_positions(self) -> dict:
        try:
            positions = self.client.get_all_positions()
            pos_dict = {}
            for pos in positions:
                pos_dict[pos.symbol] = {
                    "qty": int(float(pos.qty)),
                    "avg_entry_price": float(pos.avg_entry_price),
                    "current_price": float(pos.current_price),
                    "market_value": float(pos.market_value),
                    "unrealized_pl": float(pos.unrealized_pl),
                    "unrealized_plpc": float(pos.unrealized_plpc),
                }
            if pos_dict:
                logger.info(f"Open positions: {list(pos_dict.keys())}")
            return pos_dict
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}", exc_info=True)
            return {}

    def _submit_bracket(
        self,
        symbol: str,
        qty: int,
        limit_price: float,
        stop_loss_price: float,
        take_profit_price: float,
    ):
        order_data = LimitOrderRequest(
            symbol=symbol,
            limit_price=round(limit_price, 2),
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(take_profit_price, 2)),
            stop_loss=StopLossRequest(stop_price=round(stop_loss_price, 2)),
        )
        return self.client.submit_order(order_data)

    def submit_bracket_order(
        self,
        symbol: str,
        qty: int,
        limit_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        wait_for_fill: bool = True,
        get_requote_price=None,
    ) -> bool:
        """
        Submit bracket limit entry. Optionally wait for fill; on timeout
        cancel and requote (up to LIMIT_REQUOTE_MAX) using get_requote_price().
        """
        if config.ALLOW_MARKET_ENTRIES:
            logger.warning(
                f"{symbol}: ALLOW_MARKET_ENTRIES is on but entries still use LIMIT brackets."
            )

        attempts = 0
        max_attempts = 1 + max(0, config.LIMIT_REQUOTE_MAX)
        current_limit = limit_price
        sl = stop_loss_price
        tp = take_profit_price
        risk = limit_price - stop_loss_price
        reward = take_profit_price - limit_price

        while attempts < max_attempts:
            attempts += 1
            try:
                order = self._submit_bracket(symbol, qty, current_limit, sl, tp)
                order_id = str(order.id)
                logger.info(
                    f"BRACKET ORDER SUBMITTED | {symbol} | Qty={qty} | "
                    f"Entry=${current_limit:.2f} | SL=${sl:.2f} | "
                    f"TP=${tp:.2f} | ID={order_id} "
                    f"(attempt {attempts}/{max_attempts})"
                )

                if not wait_for_fill or config.LIMIT_FILL_TIMEOUT_SEC <= 0:
                    self._pending_limits[order_id] = {
                        "symbol": symbol,
                        "submitted_at": time.time(),
                        "limit": current_limit,
                    }
                    return True

                filled = self._wait_for_fill(order_id, config.LIMIT_FILL_TIMEOUT_SEC)
                if filled:
                    self._pending_limits.pop(order_id, None)
                    return True

                logger.warning(
                    f"{symbol}: Limit not filled in {config.LIMIT_FILL_TIMEOUT_SEC}s "
                    f"— cancelling order {order_id}"
                )
                try:
                    self.client.cancel_order_by_id(order_id)
                except Exception as ce:
                    logger.warning(f"Cancel failed for {order_id}: {ce}")

                self._pending_limits.pop(order_id, None)

                if attempts >= max_attempts:
                    logger.warning(f"{symbol}: Max requotes reached — giving up.")
                    return False

                if get_requote_price is not None:
                    new_px = get_requote_price()
                    if new_px and new_px > 0:
                        current_limit = float(new_px)
                        sl = round(current_limit - risk, 2)
                        tp = round(current_limit + reward, 2)
                        logger.info(f"{symbol}: Requoting at ${current_limit:.2f}")
                        continue
                return False

            except Exception as e:
                logger.error(
                    f"Failed to submit bracket order for {symbol}: {e}",
                    exc_info=True,
                )
                return False

        return False

    def _wait_for_fill(self, order_id: str, timeout_sec: int) -> bool:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                order = self.client.get_order_by_id(order_id)
                status = str(order.status).lower()
                if "fill" in status and "partial" not in status:
                    logger.info(f"Order {order_id} FILLED")
                    return True
                if status in ("canceled", "cancelled", "expired", "rejected"):
                    logger.warning(f"Order {order_id} ended as {status}")
                    return False
                filled_qty = float(getattr(order, "filled_qty", 0) or 0)
                if filled_qty > 0 and "partial" in status:
                    logger.info(f"Order {order_id} partially filled ({filled_qty})")
                    return True
            except Exception as e:
                logger.debug(f"Fill poll error: {e}")
            time.sleep(min(5, max(1, timeout_sec // 10)))
        return False

    def manage_pending_limits(self) -> list[str]:
        """Cancel stale unfilled parents older than LIMIT_FILL_TIMEOUT_SEC."""
        cancelled = []
        now = time.time()
        for order_id, meta in list(self._pending_limits.items()):
            age = now - meta["submitted_at"]
            if age < config.LIMIT_FILL_TIMEOUT_SEC:
                continue
            try:
                order = self.client.get_order_by_id(order_id)
                status = str(order.status).lower()
                if "fill" in status:
                    self._pending_limits.pop(order_id, None)
                    continue
                self.client.cancel_order_by_id(order_id)
                cancelled.append(meta["symbol"])
                self._pending_limits.pop(order_id, None)
                logger.warning(
                    f"Stale limit cancelled for {meta['symbol']} (age={age:.0f}s) "
                    f"— will requote on next BUY signal"
                )
            except Exception as e:
                logger.debug(f"Pending limit check failed: {e}")
                self._pending_limits.pop(order_id, None)
        return cancelled

    def close_position(self, symbol: str) -> bool:
        try:
            self.client.close_position(symbol)
            logger.info(f"Position CLOSED for {symbol}.")
            return True
        except Exception as e:
            logger.error(f"Failed to close position for {symbol}: {e}", exc_info=True)
            return False

    def cancel_all_open_orders(self) -> bool:
        try:
            self.client.cancel_orders()
            self._pending_limits.clear()
            logger.info("All open orders cancelled.")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel open orders: {e}", exc_info=True)
            return False
