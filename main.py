"""
main.py — Main Orchestrator & Web Admin Dashboard Launcher
===========================================================
Entry point for the Automated AI Stock Trading Bot.
"""

import logging
import sys
import time
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
except ImportError:
    import pytz  # type: ignore
    EASTERN = pytz.timezone("America/New_York")


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


def is_market_open() -> bool:
    now_et = datetime.now(EASTERN)
    if now_et.weekday() >= 5:
        return False
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now_et <= market_close


def log_portfolio_summary(executor: TradeExecutor):
    positions = executor.get_open_positions()
    if not positions:
        logger.info("[PORTFOLIO] No open positions.")
        return

    logger.info("[PORTFOLIO] Portfolio Summary:")
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


def run_bot():
    logger.info("=" * 70)
    logger.info("   AUTOMATED AI STOCK TRADING BOT -- STARTING UP")
    logger.info(f"   Mode: {'PAPER TRADING (Safe)' if config.PAPER_TRADING else 'LIVE TRADING'}")
    logger.info(f"   Universe: {config.STOCK_UNIVERSE}")
    logger.info(f"   Timeframe: {config.TIMEFRAME} | Loop Interval: {config.LOOP_INTERVAL_SEC}s")
    logger.info("=" * 70)

    try:
        start_dashboard_in_background(port=5000)
        logger.info("[DASHBOARD] Web Admin Dashboard running at http://localhost:5000")
    except Exception as e:
        logger.warning(f"Could not start Web Dashboard: {e}")

    if config.IS_PLACEHOLDER_KEY:
        logger.error("=" * 70)
        logger.error("[ERROR] ALPACA API KEYS NOT CONFIGURED IN .env FILE!")
        logger.error("   Please open the .env file and paste your Alpaca Paper API Keys:")
        logger.error("   ALPACA_API_KEY=PK...")
        logger.error("   ALPACA_SECRET_KEY=...")
        logger.error("   Dashboard is running at http://localhost:5000 -- waiting for keys...")
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
                logger.info("[SUCCESS] Valid Alpaca API Keys loaded from .env! Resuming bot...")

    data_feed = DataFeed()
    strategy = Strategy()
    risk_mgr = RiskManager()
    executor = TradeExecutor()

    executor.cancel_all_open_orders()
    logger.info("All modules initialized. Entering main trading loop...\n")

    while True:
        try:
            loop_start = time.time()

            if not is_market_open():
                now_et = datetime.now(EASTERN)
                logger.info(
                    f"[STATUS] Market is CLOSED ({now_et.strftime('%A %I:%M %p ET')}). "
                    f"Next check in {config.LOOP_INTERVAL_SEC}s..."
                )
                time.sleep(config.LOOP_INTERVAL_SEC)
                if now_et.hour == 0 and now_et.minute < 6:
                    risk_mgr.reset_kill_switch()
                continue

            logger.info("-" * 60)
            logger.info(
                f"[CYCLE] NEW TRADING CYCLE -- {datetime.now(EASTERN).strftime('%Y-%m-%d %I:%M:%S %p ET')}"
            )

            account = executor.get_account_info()
            if account is None:
                logger.error("Cannot retrieve account info -- skipping this cycle.")
                time.sleep(config.LOOP_INTERVAL_SEC)
                continue

            current_equity = account["equity"]
            sod_equity = account["last_equity"]

            if risk_mgr.check_daily_drawdown(current_equity, sod_equity):
                logger.critical(
                    "[KILL-SWITCH] Trading PAUSED due to daily drawdown limit breach. All open orders cancelled."
                )
                executor.cancel_all_open_orders()
                time.sleep(config.LOOP_INTERVAL_SEC)
                continue

            current_positions = executor.get_open_positions()

            for symbol in config.STOCK_UNIVERSE:
                logger.info(f"-- Scanning {symbol} " + "-" * (45 - len(symbol)))

                df = data_feed.get_historical_bars(symbol)
                if df is None or df.empty:
                    logger.warning(f"{symbol}: No data available -- skipping.")
                    continue

                df = strategy.compute_indicators(df)
                signal = strategy.generate_signal(df, symbol)

                if signal == "BUY":
                    if not risk_mgr.is_position_allowed(symbol, current_positions):
                        continue

                    quote = data_feed.get_latest_quote(symbol)
                    if quote is None:
                        logger.warning(f"{symbol}: Cannot retrieve quote -- skipping buy.")
                        continue

                    limit_price = quote["ask_price"]
                    qty = risk_mgr.calculate_position_size(current_equity, limit_price)
                    if qty <= 0:
                        logger.info(f"{symbol}: Calculated position size is 0 -- skipping.")
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
                        logger.debug(f"{symbol}: SELL signal but no position held -- skipping.")

            log_portfolio_summary(executor)

            elapsed = time.time() - loop_start
            sleep_time = max(0, config.LOOP_INTERVAL_SEC - elapsed)
            logger.info(f"[COMPLETE] Cycle complete ({elapsed:.1f}s elapsed). Next scan in {sleep_time:.0f}s.\n")
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"[ERROR] Unexpected error in main loop: {e}", exc_info=True)
            time.sleep(config.LOOP_INTERVAL_SEC)


if __name__ == "__main__":
    setup_logging()
    logger.info("Starting Automated AI Stock Trading Bot with Web Dashboard...")
    try:
        run_bot()
    except KeyboardInterrupt:
        logger.info("\nBot stopped by user (Ctrl+C). Shutting down gracefully.")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error -- bot crashed: {e}", exc_info=True)
        sys.exit(1)
