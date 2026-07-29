"""
main.py — Main Orchestrator & Web Admin Dashboard Launcher
===========================================================
Entry point for the Unified AI Stock Trading Bot.

Runs two parallel trading loops:
  1. US Market Loop  — Alpaca API (9:30 AM - 4:00 PM ET / 7:00 PM - 1:30 AM IST)
  2. India Market Loop — Angel One SmartAPI (9:15 AM - 3:30 PM IST)

Both loops share the same Strategy engine and RiskManager.
"""

import logging
import sys
import time
import threading
from datetime import datetime

import config
from data_feed import DataFeed
from strategy import Strategy
from risk_manager import RiskManager
from execution import TradeExecutor
from dashboard_server import start_dashboard_in_background

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
    IST = ZoneInfo("Asia/Kolkata")
except ImportError:
    import pytz  # type: ignore
    EASTERN = pytz.timezone("America/New_York")
    IST = pytz.timezone("Asia/Kolkata")


def setup_logging():
    log_format = "%(asctime)s | %(levelname)-8s | %(name)-18s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler("trading_bot.log", mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))
    root_logger.addHandler(file_handler)


logger = logging.getLogger("main")


# ===========================================================================
# Market Hours Detection
# ===========================================================================
def is_us_market_open() -> bool:
    """Check if US stock market is currently open (9:30 AM - 4:00 PM ET)."""
    now_et = datetime.now(EASTERN)
    if now_et.weekday() >= 5:
        return False
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now_et <= market_close


def is_india_market_open() -> bool:
    """Check if India stock market is currently open (9:15 AM - 3:30 PM IST)."""
    now_ist = datetime.now(IST)
    if now_ist.weekday() >= 5:
        return False
    market_open = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now_ist <= market_close


# ===========================================================================
# Portfolio Summary Logging
# ===========================================================================
def log_portfolio_summary(executor: TradeExecutor, market_label: str = "US"):
    positions = executor.get_open_positions()
    if not positions:
        logger.info(f"[{market_label} PORTFOLIO] No open positions.")
        return

    logger.info(f"[{market_label} PORTFOLIO] Portfolio Summary:")
    header = f"   {'Symbol':<8} {'Qty':>6} {'Entry':>10} {'Current':>10} {'P&L ($)':>12} {'P&L (%)':>8}"
    logger.info(header)
    logger.info("   " + "-" * 60)

    total_pl = 0.0
    for symbol, pos in positions.items():
        total_pl += pos["unrealized_pl"]
        logger.info(
            f"   {symbol:<8} {pos['qty']:>6} "
            f"${pos['avg_entry_price']:>9.2f} "
            f"${pos['current_price']:>9.2f} "
            f"${pos['unrealized_pl']:>11.2f} "
            f"{pos['unrealized_plpc']:>7.2%}"
        )

    logger.info("   " + "-" * 60)
    logger.info(f"   Total Unrealized P&L: ${total_pl:,.2f}")


def log_india_portfolio_summary(india_broker, market_label: str = "INDIA"):
    """Log India portfolio summary (uses INR)."""
    positions = india_broker.get_open_positions()
    if not positions:
        logger.info(f"[{market_label} PORTFOLIO] No open positions.")
        return

    logger.info(f"[{market_label} PORTFOLIO] Portfolio Summary:")
    header = f"   {'Symbol':<12} {'Qty':>6} {'Entry':>10} {'Current':>10} {'P&L':>12} {'P&L (%)':>8}"
    logger.info(header)
    logger.info("   " + "-" * 64)

    total_pl = 0.0
    for symbol, pos in positions.items():
        total_pl += pos["unrealized_pl"]
        logger.info(
            f"   {symbol:<12} {pos['qty']:>6} "
            f"Rs{pos['avg_entry_price']:>8.2f} "
            f"Rs{pos['current_price']:>8.2f} "
            f"Rs{pos['unrealized_pl']:>10.2f} "
            f"{pos['unrealized_plpc']:>7.2%}"
        )

    logger.info("   " + "-" * 64)
    logger.info(f"   Total Unrealized P&L: Rs {total_pl:,.2f}")


# ===========================================================================
# US Market Trading Loop
# ===========================================================================
def run_us_loop(data_feed, strategy, risk_mgr, executor):
    """Main US market trading loop — runs continuously."""
    logger.info("[US] US Market trading loop started")

    while True:
        try:
            loop_start = time.time()

            if not is_us_market_open():
                now_et = datetime.now(EASTERN)
                logger.info(
                    f"[US STATUS] Market is CLOSED ({now_et.strftime('%A %I:%M %p ET')}). "
                    f"Next check in {config.LOOP_INTERVAL_SEC}s..."
                )
                time.sleep(config.LOOP_INTERVAL_SEC)
                if now_et.hour == 0 and now_et.minute < 6:
                    risk_mgr.reset_kill_switch()
                continue

            logger.info("-" * 60)
            logger.info(
                f"[US CYCLE] NEW TRADING CYCLE -- {datetime.now(EASTERN).strftime('%Y-%m-%d %I:%M:%S %p ET')}"
            )

            account = executor.get_account_info()
            if account is None:
                logger.error("[US] Cannot retrieve account info -- skipping this cycle.")
                time.sleep(config.LOOP_INTERVAL_SEC)
                continue

            current_equity = account["equity"]
            sod_equity = account["last_equity"]

            if risk_mgr.check_daily_drawdown(current_equity, sod_equity):
                logger.critical(
                    "[US KILL-SWITCH] Trading PAUSED due to daily drawdown limit breach."
                )
                executor.cancel_all_open_orders()
                time.sleep(config.LOOP_INTERVAL_SEC)
                continue

            current_positions = executor.get_open_positions()

            for symbol in config.STOCK_UNIVERSE:
                logger.info(f"[US] -- Scanning {symbol} " + "-" * (40 - len(symbol)))

                df = data_feed.get_historical_bars(symbol)
                if df is None or df.empty:
                    logger.warning(f"[US] {symbol}: No data available -- skipping.")
                    continue

                df = strategy.compute_indicators(df)
                signal = strategy.generate_signal(df, symbol)

                if signal == "BUY":
                    if not risk_mgr.is_position_allowed(symbol, current_positions):
                        continue

                    quote = data_feed.get_latest_quote(symbol)
                    if quote is None:
                        logger.warning(f"[US] {symbol}: Cannot retrieve quote -- skipping buy.")
                        continue

                    limit_price = quote["ask_price"]
                    qty = risk_mgr.calculate_position_size(current_equity, limit_price)
                    if qty <= 0:
                        logger.info(f"[US] {symbol}: Calculated position size is 0 -- skipping.")
                        continue

                    sl_price = risk_mgr.get_stop_loss_price(limit_price)
                    tp_price = risk_mgr.get_take_profit_price(limit_price)

                    executor.submit_bracket_order(
                        symbol=symbol,
                        qty=qty,
                        limit_price=limit_price,
                        stop_loss_price=sl_price,
                        take_profit_price=tp_price,
                    )

                elif signal == "SELL":
                    if symbol in current_positions:
                        executor.close_position(symbol)
                    else:
                        logger.debug(f"[US] {symbol}: SELL signal but no position held -- skipping.")

            log_portfolio_summary(executor, "US")

            elapsed = time.time() - loop_start
            sleep_time = max(0, config.LOOP_INTERVAL_SEC - elapsed)
            logger.info(f"[US COMPLETE] Cycle complete ({elapsed:.1f}s). Next in {sleep_time:.0f}s.\n")
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"[US ERROR] Unexpected error in US loop: {e}", exc_info=True)
            time.sleep(config.LOOP_INTERVAL_SEC)


# ===========================================================================
# India Market Trading Loop
# ===========================================================================
def run_india_loop(strategy, risk_mgr):
    """Main India market trading loop — runs continuously."""
    from india_broker import IndiaBroker

    logger.info("[INDIA] India Market trading loop starting...")

    try:
        india_broker = IndiaBroker()
    except Exception as e:
        logger.error(f"[INDIA] Failed to initialize India broker: {e}")
        return

    india_broker.cancel_all_open_orders()
    logger.info("[INDIA] India modules initialized. Entering India trading loop...")

    while True:
        try:
            loop_start = time.time()

            if not is_india_market_open():
                now_ist = datetime.now(IST)
                logger.info(
                    f"[INDIA STATUS] Market is CLOSED ({now_ist.strftime('%A %I:%M %p IST')}). "
                    f"Next check in {config.INDIA_LOOP_INTERVAL_SEC}s..."
                )

                # Re-login at 9:10 AM IST for fresh session
                if now_ist.hour == 9 and 10 <= now_ist.minute < 15:
                    logger.info("[INDIA] Pre-market session refresh...")
                    india_broker.login()

                time.sleep(config.INDIA_LOOP_INTERVAL_SEC)
                continue

            logger.info("=" * 60)
            logger.info(
                f"[INDIA CYCLE] NEW TRADING CYCLE -- {datetime.now(IST).strftime('%Y-%m-%d %I:%M:%S %p IST')}"
            )

            # Check SL/TP for existing positions first
            closed = india_broker.check_sl_tp(risk_mgr)
            if closed:
                logger.info(f"[INDIA] Closed positions due to SL/TP: {closed}")

            # Get account info for position sizing
            account = india_broker.get_account_info()
            if account is None:
                logger.error("[INDIA] Cannot retrieve account info -- skipping cycle.")
                time.sleep(config.INDIA_LOOP_INTERVAL_SEC)
                continue

            current_equity = account["equity"]
            current_positions = india_broker.get_open_positions()

            for symbol in config.INDIA_STOCK_UNIVERSE:
                logger.info(f"[INDIA] -- Scanning {symbol} " + "-" * (40 - len(symbol)))

                df = india_broker.get_historical_bars(symbol)
                if df is None or df.empty:
                    logger.warning(f"[INDIA] {symbol}: No data available -- skipping.")
                    continue

                df = strategy.compute_indicators(df)
                signal = strategy.generate_signal(df, symbol)

                if signal == "BUY":
                    if not risk_mgr.is_position_allowed(symbol, current_positions):
                        continue

                    quote = india_broker.get_latest_quote(symbol)
                    if quote is None:
                        logger.warning(f"[INDIA] {symbol}: Cannot retrieve quote -- skipping buy.")
                        continue

                    limit_price = quote["ltp"]
                    qty = risk_mgr.calculate_position_size(current_equity, limit_price)
                    if qty <= 0:
                        logger.info(f"[INDIA] {symbol}: Calculated position size is 0 -- skipping.")
                        continue

                    india_broker.place_buy_order(
                        symbol=symbol,
                        qty=qty,
                        limit_price=limit_price,
                    )

                elif signal == "SELL":
                    if symbol in current_positions:
                        india_broker.close_position(symbol)
                    else:
                        logger.debug(f"[INDIA] {symbol}: SELL signal but no position -- skipping.")

            log_india_portfolio_summary(india_broker, "INDIA")

            elapsed = time.time() - loop_start
            sleep_time = max(0, config.INDIA_LOOP_INTERVAL_SEC - elapsed)
            logger.info(f"[INDIA COMPLETE] Cycle complete ({elapsed:.1f}s). Next in {sleep_time:.0f}s.\n")
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"[INDIA ERROR] Unexpected error in India loop: {e}", exc_info=True)
            time.sleep(config.INDIA_LOOP_INTERVAL_SEC)


# ===========================================================================
# Main Entry Point
# ===========================================================================
def run_bot():
    logger.info("=" * 70)
    logger.info("   UNIFIED AI STOCK TRADING BOT -- STARTING UP")
    logger.info(f"   US Mode: {'PAPER TRADING (Safe)' if config.PAPER_TRADING else 'LIVE TRADING'}")
    logger.info(f"   US Universe: {config.STOCK_UNIVERSE}")
    logger.info(f"   India Enabled: {config.INDIA_ENABLED}")
    if config.INDIA_ENABLED:
        logger.info(f"   India Universe: {config.INDIA_STOCK_UNIVERSE}")
    logger.info(f"   Loop Intervals: US={config.LOOP_INTERVAL_SEC}s | India={config.INDIA_LOOP_INTERVAL_SEC}s")
    logger.info("=" * 70)

    # Start Web Dashboard
    try:
        start_dashboard_in_background(port=5000)
        logger.info("[DASHBOARD] Unified Web Dashboard running at http://localhost:5000")
    except Exception as e:
        logger.warning(f"Could not start Web Dashboard: {e}")

    # Wait for valid Alpaca API keys
    if config.IS_PLACEHOLDER_KEY:
        logger.error("=" * 70)
        logger.error("[ERROR] ALPACA API KEYS NOT CONFIGURED IN .env FILE!")
        logger.error("   Dashboard is running — waiting for keys...")
        logger.error("=" * 70)

        while config.IS_PLACEHOLDER_KEY:
            time.sleep(10)
            from dotenv import load_dotenv
            load_dotenv(override=True)
            import os
            config.ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "").strip()
            config.ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "").strip()
            config.IS_PLACEHOLDER_KEY = (
                not config.ALPACA_API_KEY
                or "your_api_key_here" in config.ALPACA_API_KEY
            )
            if not config.IS_PLACEHOLDER_KEY:
                logger.info("[SUCCESS] Valid Alpaca API Keys loaded!")

    # Initialize shared components
    data_feed = DataFeed()
    strategy = Strategy()
    risk_mgr = RiskManager()
    executor = TradeExecutor()

    executor.cancel_all_open_orders()
    logger.info("US modules initialized. Starting trading loops...\n")

    # Start India loop in a separate thread if enabled
    if config.INDIA_ENABLED:
        india_thread = threading.Thread(
            target=run_india_loop,
            args=(strategy, risk_mgr),
            daemon=True,
            name="IndiaMarketLoop",
        )
        india_thread.start()
        logger.info("[INDIA] India Market trading loop started in background thread")
    else:
        logger.info("[INDIA] India trading DISABLED — no Angel One credentials in .env")

    # Run US loop in main thread
    run_us_loop(data_feed, strategy, risk_mgr, executor)


if __name__ == "__main__":
    setup_logging()
    logger.info("Starting Unified AI Stock Trading Bot (US + India)...")
    try:
        run_bot()
    except KeyboardInterrupt:
        logger.info("\nBot stopped by user (Ctrl+C). Shutting down gracefully.")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error -- bot crashed: {e}", exc_info=True)
        sys.exit(1)
