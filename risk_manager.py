"""
risk_manager.py — Risk Management Module
==========================================
Enforces strict capital preservation rules to protect the portfolio:

  1. Position Sizing  — Max 5% of equity per single stock position.
  2. Hard Stop-Loss   — Automatic exit at 2% below entry price.
  3. Take-Profit      — Automatic exit at 4% above entry price.
  4. Drawdown Kill-Switch — Pause ALL trading if daily loss exceeds 3%.
  5. Duplicate Prevention — Only one position per symbol at a time.

All thresholds are configurable via config.py.
"""

import logging

import config

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Strict risk controls to protect capital.

    This module is the "safety net" of the bot. Even if the strategy
    generates a signal, the RiskManager can block the trade if it
    violates any risk rule.
    """

    def __init__(self):
        """Initialize risk parameters from config."""
        self.max_position_pct = config.MAX_POSITION_PCT
        self.stop_loss_pct = config.STOP_LOSS_PCT
        self.take_profit_pct = config.TAKE_PROFIT_PCT
        self.daily_drawdown_limit = config.DAILY_DRAWDOWN_LIMIT

        # Internal flag — set to True when daily drawdown limit is breached
        self._kill_switch_active: bool = False

        logger.info(
            f"RiskManager initialized — "
            f"MaxPos={self.max_position_pct:.0%}, "
            f"SL={self.stop_loss_pct:.0%}, "
            f"TP={self.take_profit_pct:.0%}, "
            f"DailyDD={self.daily_drawdown_limit:.0%}"
        )

    # -----------------------------------------------------------------------
    # Position Sizing
    # -----------------------------------------------------------------------
    def calculate_position_size(self, equity: float, price: float) -> int:
        """
        Calculate the maximum number of shares to buy for a single position.

        Formula: shares = floor((equity × MAX_POSITION_PCT) / price)
        Example: $100,000 equity × 5% = $5,000 budget → $5,000 / $150 = 33 shares

        Args:
            equity: Current total portfolio equity in dollars.
            price:  Current share price (ask price for buys).

        Returns:
            Integer number of shares (floored). Returns 0 if price is invalid.
        """
        if price <= 0:
            logger.warning("Invalid price for position sizing — returning 0 shares.")
            return 0

        max_dollar_amount = equity * self.max_position_pct
        shares = int(max_dollar_amount // price)

        logger.info(
            f"Position sizing: "
            f"Equity=${equity:,.2f} × {self.max_position_pct:.0%} "
            f"= ${max_dollar_amount:,.2f} budget → "
            f"{shares} shares @ ${price:.2f}/share"
        )
        return shares

    # -----------------------------------------------------------------------
    # Stop-Loss & Take-Profit Price Levels
    # -----------------------------------------------------------------------
    def get_stop_loss_price(self, entry_price: float) -> float:
        """
        Calculate the hard stop-loss price.

        Example: Entry at $150.00, SL=2% → Stop at $147.00

        Args:
            entry_price: The limit price at which the position is entered.

        Returns:
            Stop-loss price rounded to 2 decimal places.
        """
        sl_price = round(entry_price * (1 - self.stop_loss_pct), 2)
        logger.debug(
            f"Stop-loss: ${entry_price:.2f} × "
            f"(1 − {self.stop_loss_pct:.0%}) = ${sl_price:.2f}"
        )
        return sl_price

    def get_take_profit_price(self, entry_price: float) -> float:
        """
        Calculate the take-profit price.

        Example: Entry at $150.00, TP=4% → Target at $156.00

        Args:
            entry_price: The limit price at which the position is entered.

        Returns:
            Take-profit price rounded to 2 decimal places.
        """
        tp_price = round(entry_price * (1 + self.take_profit_pct), 2)
        logger.debug(
            f"Take-profit: ${entry_price:.2f} × "
            f"(1 + {self.take_profit_pct:.0%}) = ${tp_price:.2f}"
        )
        return tp_price

    # -----------------------------------------------------------------------
    # Daily Drawdown Kill-Switch
    # -----------------------------------------------------------------------
    def check_daily_drawdown(
        self, current_equity: float, start_of_day_equity: float
    ) -> bool:
        """
        Check if daily drawdown exceeds the kill-switch threshold.

        If the portfolio has lost more than DAILY_DRAWDOWN_LIMIT (default 3%)
        from the start-of-day equity, ALL trading is paused immediately.

        Args:
            current_equity:       Current portfolio equity.
            start_of_day_equity:  Portfolio equity at market open (previous close).

        Returns:
            True if drawdown limit is breached (trading should STOP).
            False if drawdown is within acceptable range (trading continues).
        """
        if start_of_day_equity <= 0:
            logger.error(
                "Start-of-day equity is zero or negative — "
                "cannot compute drawdown. Halting for safety."
            )
            return True  # Fail-safe: stop trading

        drawdown = (start_of_day_equity - current_equity) / start_of_day_equity

        if drawdown >= self.daily_drawdown_limit:
            self._kill_switch_active = True
            logger.critical(
                f"🚨 DAILY DRAWDOWN KILL-SWITCH TRIGGERED! "
                f"Drawdown = {drawdown:.2%} (Limit = {self.daily_drawdown_limit:.0%}) | "
                f"SOD Equity = ${start_of_day_equity:,.2f} → "
                f"Current = ${current_equity:,.2f} | "
                f"ALL TRADING PAUSED."
            )
            return True

        logger.info(
            f"Daily drawdown check: {drawdown:.2%} "
            f"(Limit = {self.daily_drawdown_limit:.0%}) — ✅ OK"
        )
        return False

    @property
    def is_kill_switch_active(self) -> bool:
        """Check if the daily drawdown kill-switch has been triggered."""
        return self._kill_switch_active

    def reset_kill_switch(self):
        """
        Reset the kill-switch flag.

        Call this at the start of a new trading day so the bot can
        resume trading after an overnight reset.
        """
        self._kill_switch_active = False
        logger.info("Daily drawdown kill-switch has been reset for new trading day.")

    # -----------------------------------------------------------------------
    # Duplicate Position Check
    # -----------------------------------------------------------------------
    def is_position_allowed(
        self, symbol: str, current_positions: dict
    ) -> bool:
        """
        Check if opening a new position for this symbol is allowed.

        Rule: Only one position per symbol at a time. If we already
        hold shares of a stock, we don't add to the position.

        Args:
            symbol:             Stock ticker to check (e.g., "AAPL").
            current_positions:  Dict of {symbol: position_data} for current holdings.

        Returns:
            True if a new position is allowed, False if already held.
        """
        if symbol in current_positions:
            logger.info(
                f"{symbol}: Already holding a position "
                f"({current_positions[symbol].get('qty', '?')} shares) — "
                f"skipping new entry."
            )
            return False
        return True
