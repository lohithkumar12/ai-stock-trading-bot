"""
execution.py — Trade Execution Module
========================================
Handles all order submission and position management via Alpaca's Trading API.

Key Principles:
  - NEVER uses market orders (no slippage risk).
  - All entries are Bracket Orders (Limit Entry + Stop-Loss + Take-Profit).
  - Full error handling with structured logging for every API call.

Order Flow:
  1. Submit bracket order → entry fills at limit price
  2. If price drops → stop-loss leg triggers automatically
  3. If price rises → take-profit leg triggers automatically
  4. Bot never needs to manually manage exits for bracket orders
"""

import logging

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
    """
    Manages all trade execution through Alpaca's Trading API.

    Provides methods for:
      - Submitting bracket orders (limit entry + SL + TP)
      - Querying open positions
      - Retrieving account info (equity, buying power)
      - Closing positions and cancelling orders
    """

    def __init__(self):
        """Initialize the Alpaca trading client in paper or live mode."""
        self.client = TradingClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
            paper=config.PAPER_TRADING,
        )
        mode = "📝 PAPER" if config.PAPER_TRADING else "⚠️  LIVE"
        logger.info(f"TradeExecutor initialized — Mode: {mode}")

    # -----------------------------------------------------------------------
    # Account Information
    # -----------------------------------------------------------------------
    def get_account_info(self) -> dict | None:
        """
        Retrieve current account information from Alpaca.

        Returns:
            Dict with keys:
              - equity:          Total portfolio value (cash + positions)
              - buying_power:    Available funds for new trades
              - last_equity:     Previous day's closing equity (for drawdown calc)
              - cash:            Cash balance
              - portfolio_value: Total portfolio value
            Returns None on failure.
        """
        try:
            account = self.client.get_account()
            info = {
                "equity":          float(account.equity),
                "buying_power":    float(account.buying_power),
                "last_equity":     float(account.last_equity),
                "cash":            float(account.cash),
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

    # -----------------------------------------------------------------------
    # Position Tracking
    # -----------------------------------------------------------------------
    def get_open_positions(self) -> dict:
        """
        Get all currently held positions.

        Returns:
            Dict of {symbol: position_data} where position_data contains:
              - qty:              Number of shares held
              - avg_entry_price:  Average cost basis
              - current_price:    Latest market price
              - market_value:     Total position value
              - unrealized_pl:    Unrealized profit/loss in dollars
              - unrealized_plpc:  Unrealized P&L as a percentage
            Returns empty dict on failure.
        """
        try:
            positions = self.client.get_all_positions()
            pos_dict = {}

            for pos in positions:
                pos_dict[pos.symbol] = {
                    "qty":              int(pos.qty),
                    "avg_entry_price":  float(pos.avg_entry_price),
                    "current_price":    float(pos.current_price),
                    "market_value":     float(pos.market_value),
                    "unrealized_pl":    float(pos.unrealized_pl),
                    "unrealized_plpc":  float(pos.unrealized_plpc),
                }

            if pos_dict:
                logger.info(f"Open positions: {list(pos_dict.keys())}")
            else:
                logger.debug("No open positions.")

            return pos_dict

        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}", exc_info=True)
            return {}

    # -----------------------------------------------------------------------
    # Bracket Order Submission
    # -----------------------------------------------------------------------
    def submit_bracket_order(
        self,
        symbol: str,
        qty: int,
        limit_price: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> bool:
        """
        Submit a bracket order: Limit Entry + Stop-Loss + Take-Profit.

        This is the ONLY order type used by the bot. A bracket order ensures
        that once the entry fills, protective stop-loss and take-profit orders
        are automatically placed — no manual intervention needed.

        Args:
            symbol:           Stock ticker (e.g., "AAPL").
            qty:              Number of shares to buy.
            limit_price:      Limit price for the entry leg.
            stop_loss_price:  Stop-loss trigger price (exit if price drops here).
            take_profit_price: Take-profit limit price (exit if price rises here).

        Returns:
            True if order submitted successfully, False otherwise.
        """
        try:
            order_data = LimitOrderRequest(
                symbol=symbol,
                limit_price=round(limit_price, 2),
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(
                    limit_price=round(take_profit_price, 2)
                ),
                stop_loss=StopLossRequest(
                    stop_price=round(stop_loss_price, 2)
                ),
            )

            order = self.client.submit_order(order_data)

            logger.info(
                f"✅ BRACKET ORDER SUBMITTED | {symbol} | "
                f"Qty={qty} | Entry=${limit_price:.2f} | "
                f"SL=${stop_loss_price:.2f} | TP=${take_profit_price:.2f} | "
                f"Order ID={order.id}"
            )
            return True

        except Exception as e:
            logger.error(
                f"❌ Failed to submit bracket order for {symbol}: {e}",
                exc_info=True,
            )
            return False

    # -----------------------------------------------------------------------
    # Position Closing
    # -----------------------------------------------------------------------
    def close_position(self, symbol: str) -> bool:
        """
        Close (liquidate) an existing position for a symbol.

        Alpaca handles the actual sell order — this sends a request
        to close the entire position at market price.

        Args:
            symbol: Stock ticker to close (e.g., "AAPL").

        Returns:
            True if close request succeeded, False otherwise.
        """
        try:
            self.client.close_position(symbol)
            logger.info(f"✅ Position CLOSED for {symbol}.")
            return True

        except Exception as e:
            logger.error(
                f"❌ Failed to close position for {symbol}: {e}",
                exc_info=True,
            )
            return False

    # -----------------------------------------------------------------------
    # Order Cancellation
    # -----------------------------------------------------------------------
    def cancel_all_open_orders(self) -> bool:
        """
        Cancel all pending/open orders.

        Called on:
          - Bot startup (clear stale orders from previous runs)
          - Daily drawdown kill-switch activation
          - Graceful shutdown

        Returns:
            True if cancellation succeeded, False otherwise.
        """
        try:
            self.client.cancel_orders()
            logger.info("🗑️  All open orders cancelled.")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel open orders: {e}", exc_info=True)
            return False
