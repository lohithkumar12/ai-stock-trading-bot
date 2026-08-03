"""
main.py — Main Orchestrator & Web Admin Dashboard Launcher
===========================================================
24/7 dual-market bot:
  US    → Alpaca PAPER (fake USD) + live US prices
  India → Angel One PAPER SIM (fake INR) + live NSE prices
          (or real INR when LIVE_TRADING is armed)

Dashboard tabs: US | India | Combined
Process stays alive around the clock; trades only during market hours.
"""

import logging
import sys
import time
import threading
from datetime import datetime

import config
from strategy import create_strategy, RelativeStrengthFilter
from risk_manager import RiskManager
from dashboard_server import start_dashboard_in_background
import trade_journal

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


def is_us_market_open() -> bool:
    now_et = datetime.now(EASTERN)
    if now_et.weekday() >= 5:
        return False
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now_et <= market_close


def is_india_market_open() -> bool:
    now_ist = datetime.now(IST)
    if now_ist.weekday() >= 5:
        return False
    market_open = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now_ist <= market_close


def log_portfolio_summary(executor, market_label: str = "US"):
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


def _refresh_rs_filter(rs_filter, symbol_dfs: dict):
    if rs_filter is not None and config.USE_RELATIVE_STRENGTH:
        rs_filter.update_scores(symbol_dfs)


def run_us_loop(data_feed, strategy, risk_mgr, executor, rs_filter=None):
    logger.info("[US] US Market trading loop started (24/7 process)")
    last_reset_date = None

    while True:
        try:
            loop_start = time.time()
            now_et = datetime.now(EASTERN)

            if last_reset_date != now_et.date():
                risk_mgr.reset_kill_switch()
                last_reset_date = now_et.date()
                logger.info(f"[US] New day {now_et.date()} — kill-switch reset")

            if not is_us_market_open():
                logger.info(
                    f"[US STATUS] Market CLOSED ({now_et.strftime('%A %I:%M %p ET')}). "
                    f"Bot still alive — next check in {config.LOOP_INTERVAL_SEC}s..."
                )
                time.sleep(config.LOOP_INTERVAL_SEC)
                continue

            logger.info("-" * 60)
            logger.info(
                f"[US CYCLE] {now_et.strftime('%Y-%m-%d %I:%M:%S %p ET')} "
                f"| Mode={'PAPER' if config.PAPER_TRADING else 'LIVE'} "
                f"| Strategy={strategy.name}"
            )

            # Avoid open/close noise for new entries
            tradable_window = risk_mgr.is_tradable_session(
                now_et, market_open_hm=(9, 30), market_close_hm=(16, 0)
            )

            account = executor.get_account_info()
            if account is None:
                logger.error("[US] Cannot retrieve account info -- skipping this cycle.")
                time.sleep(config.LOOP_INTERVAL_SEC)
                continue

            current_equity = account["equity"]
            sod_equity = account["last_equity"]
            trade_journal.snapshot_equity("US", current_equity)

            if risk_mgr.check_daily_drawdown(current_equity, sod_equity):
                logger.critical("[US KILL-SWITCH] Trading PAUSED (daily drawdown).")
                executor.cancel_all_open_orders()
                time.sleep(config.LOOP_INTERVAL_SEC)
                continue

            executor.manage_pending_limits()
            current_positions = executor.get_open_positions()

            # Pre-fetch bars for RS ranking + signals
            bar_cache: dict = {}
            for symbol in config.STOCK_UNIVERSE:
                df = data_feed.get_historical_bars(symbol)
                if df is not None and not df.empty:
                    bar_cache[symbol] = strategy.compute_indicators(df)
            _refresh_rs_filter(rs_filter, bar_cache)

            for symbol in config.STOCK_UNIVERSE:
                logger.info(f"[US] -- Scanning {symbol} " + "-" * (40 - len(symbol)))

                df = bar_cache.get(symbol)
                if df is None or df.empty:
                    logger.warning(f"[US] {symbol}: No data — skipping.")
                    continue

                signal = strategy.generate_signal(df, symbol)
                atr = strategy.latest_atr(df)

                # Trailing management for open positions
                if symbol in current_positions:
                    pos = current_positions[symbol]
                    if symbol not in risk_mgr._trade_meta:
                        sl0 = risk_mgr.get_stop_loss_price(pos["avg_entry_price"], atr)
                        risk_mgr.register_trade(
                            symbol, pos["avg_entry_price"], sl0, atr
                        )
                    risk_mgr.update_trailing_stop(
                        symbol, pos["current_price"], atr
                    )

                if signal == "BUY":
                    if not tradable_window:
                        continue
                    if not risk_mgr.is_position_allowed(symbol, current_positions):
                        continue

                    quote = data_feed.get_latest_quote(symbol)
                    if quote is None:
                        continue

                    limit_price = quote["ask_price"]
                    if limit_price <= 0:
                        continue

                    sl = risk_mgr.get_stop_loss_price(limit_price, atr)
                    tp = risk_mgr.get_take_profit_price(
                        limit_price, stop_loss_price=sl, atr=atr
                    )
                    stop_dist = limit_price - sl
                    qty = risk_mgr.calculate_position_size(
                        current_equity, limit_price, stop_distance=stop_dist
                    )
                    if qty <= 0:
                        continue

                    def _requote():
                        q = data_feed.get_latest_quote(symbol)
                        return q["ask_price"] if q else None

                    ok = executor.submit_bracket_order(
                        symbol=symbol,
                        qty=qty,
                        limit_price=limit_price,
                        stop_loss_price=sl,
                        take_profit_price=tp,
                        wait_for_fill=False,
                        get_requote_price=_requote,
                    )
                    if ok:
                        risk_mgr.register_trade(symbol, limit_price, sl, atr)
                        trade_journal.record_entry(
                            "US",
                            symbol,
                            qty,
                            limit_price,
                            stop_price=sl,
                            take_profit=tp,
                            reason="signal_buy",
                            strategy=strategy.name,
                            meta={"atr": atr},
                        )
                        current_positions[symbol] = {"qty": qty}

                elif signal == "SELL" and symbol in current_positions:
                    pos = current_positions[symbol]
                    px = pos.get("current_price") or pos.get("avg_entry_price")
                    if executor.close_position(symbol):
                        trade_journal.record_exit(
                            "US", symbol, float(px), reason="signal_sell"
                        )
                        risk_mgr.clear_trade(symbol)

            log_portfolio_summary(executor, "US")

            elapsed = time.time() - loop_start
            sleep_time = max(0, config.LOOP_INTERVAL_SEC - elapsed)
            logger.info(f"[US COMPLETE] Cycle done ({elapsed:.1f}s). Next in {sleep_time:.0f}s.\n")
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"[US ERROR] {e}", exc_info=True)
            time.sleep(config.LOOP_INTERVAL_SEC)


def run_india_loop(strategy, risk_mgr, rs_filter=None):
    from india_broker import IndiaBroker

    logger.info("[INDIA] India Market trading loop starting (24/7 process)...")

    try:
        india_broker = IndiaBroker()
    except Exception as e:
        logger.error(f"[INDIA] Failed to initialize India broker: {e}")
        return

    if not india_broker.is_logged_in:
        logger.error(
            f"[INDIA] Login failed: {india_broker.last_error}. "
            "Need Angel One login for LIVE NSE data even in paper mode."
        )
        return

    india_broker.cancel_all_open_orders()

    start_of_day_equity = None
    last_reset_date = None
    paper = india_broker.paper is not None

    logger.info(
        f"[INDIA] Ready | Mode={'PAPER SIM + live NSE data' if paper else 'LIVE REAL MONEY'} "
        f"| Strategy={strategy.name}"
    )

    while True:
        try:
            loop_start = time.time()
            now_ist = datetime.now(IST)

            if last_reset_date != now_ist.date():
                risk_mgr.reset_kill_switch()
                start_of_day_equity = None
                last_reset_date = now_ist.date()
                if india_broker.paper is not None:
                    india_broker.paper.start_of_day_equity = None
                logger.info(f"[INDIA] New day {now_ist.date()} — kill-switch reset")

            if not is_india_market_open():
                logger.info(
                    f"[INDIA STATUS] Market CLOSED ({now_ist.strftime('%A %I:%M %p IST')}). "
                    f"Bot still alive — next check in {config.INDIA_LOOP_INTERVAL_SEC}s..."
                )
                if now_ist.hour == 9 and 10 <= now_ist.minute < 15:
                    india_broker.login()
                time.sleep(config.INDIA_LOOP_INTERVAL_SEC)
                continue

            logger.info("=" * 60)
            logger.info(
                f"[INDIA CYCLE] {now_ist.strftime('%Y-%m-%d %I:%M:%S %p IST')} | "
                f"Mode={'PAPER' if paper else 'LIVE'} | Strategy={strategy.name}"
            )

            closed = india_broker.check_sl_tp(risk_mgr)
            if closed:
                logger.info(f"[INDIA] Closed via SL/TP: {closed}")

            account = india_broker.get_account_info()
            if account is None:
                logger.error("[INDIA] Cannot retrieve account info — skipping.")
                time.sleep(config.INDIA_LOOP_INTERVAL_SEC)
                continue

            current_equity = account["equity"]
            sod = account.get("last_equity") or start_of_day_equity
            if sod is None or sod <= 0:
                sod = current_equity
                start_of_day_equity = current_equity
            else:
                start_of_day_equity = sod

            trade_journal.snapshot_equity("INDIA", current_equity)

            if risk_mgr.check_daily_drawdown(current_equity, start_of_day_equity):
                logger.critical("[INDIA KILL-SWITCH] Trading PAUSED (daily drawdown).")
                india_broker.cancel_all_open_orders()
                time.sleep(config.INDIA_LOOP_INTERVAL_SEC)
                continue

            if risk_mgr.is_kill_switch_active:
                time.sleep(config.INDIA_LOOP_INTERVAL_SEC)
                continue

            tradable_window = risk_mgr.is_tradable_session(
                now_ist, market_open_hm=(9, 15), market_close_hm=(15, 30)
            )

            current_positions = india_broker.get_open_positions()

            bar_cache: dict = {}
            for symbol in config.INDIA_STOCK_UNIVERSE:
                df = india_broker.get_historical_bars(symbol)
                if df is not None and not df.empty:
                    bar_cache[symbol] = strategy.compute_indicators(df)
            _refresh_rs_filter(rs_filter, bar_cache)

            for symbol in config.INDIA_STOCK_UNIVERSE:
                logger.info(f"[INDIA] -- Scanning {symbol} " + "-" * (40 - len(symbol)))

                df = bar_cache.get(symbol)
                if df is None or df.empty:
                    logger.warning(f"[INDIA] {symbol}: No data — skipping.")
                    continue

                signal = strategy.generate_signal(df, symbol)
                atr = strategy.latest_atr(df)

                if signal == "BUY":
                    if not tradable_window:
                        continue
                    if not risk_mgr.is_position_allowed(symbol, current_positions):
                        continue

                    quote = india_broker.get_latest_quote(symbol)
                    if quote is None:
                        continue

                    sizing_equity = min(
                        current_equity,
                        float(account.get("available_cash") or current_equity),
                    )
                    limit_price = quote["ltp"]
                    if limit_price <= 0:
                        continue

                    sl = risk_mgr.get_stop_loss_price(limit_price, atr)
                    tp = risk_mgr.get_take_profit_price(
                        limit_price, stop_loss_price=sl, atr=atr
                    )
                    stop_dist = limit_price - sl
                    qty = risk_mgr.calculate_position_size(
                        sizing_equity, limit_price, stop_distance=stop_dist
                    )
                    if qty <= 0:
                        continue

                    order_id = india_broker.place_buy_order(
                        symbol=symbol,
                        qty=qty,
                        limit_price=limit_price,
                        stop_loss_price=sl,
                        take_profit_price=tp,
                        atr=atr,
                    )
                    if order_id:
                        risk_mgr.register_trade(symbol, limit_price, sl, atr)
                        trade_journal.record_entry(
                            "INDIA",
                            symbol,
                            qty,
                            limit_price,
                            stop_price=sl,
                            take_profit=tp,
                            reason="signal_buy",
                            strategy=strategy.name,
                            meta={"atr": atr, "order_id": order_id},
                        )
                        current_positions[symbol] = {"qty": qty}

                elif signal == "SELL" and symbol in current_positions:
                    pos = current_positions[symbol]
                    px = pos.get("current_price") or pos.get("avg_entry_price")
                    if india_broker.close_position(symbol):
                        trade_journal.record_exit(
                            "INDIA", symbol, float(px), reason="signal_sell"
                        )
                        risk_mgr.clear_trade(symbol)

            log_india_portfolio_summary(india_broker, "INDIA")

            elapsed = time.time() - loop_start
            sleep_time = max(0, config.INDIA_LOOP_INTERVAL_SEC - elapsed)
            logger.info(f"[INDIA COMPLETE] Cycle done ({elapsed:.1f}s). Next in {sleep_time:.0f}s.\n")
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"[INDIA ERROR] {e}", exc_info=True)
            time.sleep(config.INDIA_LOOP_INTERVAL_SEC)


def run_bot():
    logger.info("=" * 70)
    logger.info("   AI QUANT BOT — 24/7 DUAL MARKET")
    logger.info(
        f"   US: enabled={config.US_ENABLED} | "
        f"paper={config.PAPER_TRADING} | keys_ok={not config.IS_PLACEHOLDER_KEY}"
    )
    logger.info(
        f"   India: enabled={config.INDIA_ENABLED} | "
        f"paper_sim={config.INDIA_PAPER} | live_armed={config.LIVE_CONFIRMED}"
    )
    logger.info(
        f"   Strategy={config.STRATEGY_NAME} | RS={config.USE_RELATIVE_STRENGTH} | "
        f"Risk/trade={config.RISK_PER_TRADE:.2%} | ATR_SL={config.ATR_STOP_MULT}x | "
        f"TP={config.TAKE_PROFIT_R}R | MaxOpen={config.MAX_OPEN_POSITIONS}"
    )
    logger.info("=" * 70)

    if not config.INDIA_ENABLED and (not config.US_ENABLED or config.IS_PLACEHOLDER_KEY):
        logger.critical("No markets configured. Add Alpaca and/or Angel One keys to .env")
        return

    if config.LIVE_CONFIRMED:
        logger.critical("!!! INDIA REAL MONEY MODE ARMED !!!")
    elif config.INDIA_PAPER:
        logger.info("India PAPER SIM on — live NSE data, fake INR (safe for testing)")

    trade_journal.init_db()

    try:
        start_dashboard_in_background(port=5000)
        logger.info("[DASHBOARD] http://localhost:5000  (US / India / Combined tabs)")
    except Exception as e:
        logger.warning(f"Dashboard failed to start: {e}")

    us_rs = RelativeStrengthFilter() if config.USE_RELATIVE_STRENGTH else None
    india_rs = RelativeStrengthFilter() if config.USE_RELATIVE_STRENGTH else None
    us_strategy = create_strategy("US", rs_filter=us_rs)
    india_strategy = create_strategy("INDIA", rs_filter=india_rs)
    us_risk = RiskManager(market="US")
    india_risk = RiskManager(market="INDIA")

    if config.US_ENABLED and not config.IS_PLACEHOLDER_KEY:
        from data_feed import DataFeed
        from execution import TradeExecutor

        data_feed = DataFeed()
        executor = TradeExecutor()
        executor.cancel_all_open_orders()
        us_thread = threading.Thread(
            target=run_us_loop,
            args=(data_feed, us_strategy, us_risk, executor, us_rs),
            daemon=True,
            name="USMarketLoop",
        )
        us_thread.start()
        logger.info("[US] Background loop started (Alpaca paper + live data)")
    else:
        logger.warning("[US] Disabled or missing Alpaca keys")

    if config.INDIA_ENABLED:
        india_thread = threading.Thread(
            target=run_india_loop,
            args=(india_strategy, india_risk, india_rs),
            daemon=True,
            name="IndiaMarketLoop",
        )
        india_thread.start()
        logger.info("[INDIA] Background loop started (Angel One + paper/live)")
    else:
        logger.warning("[INDIA] Disabled — missing Angel One credentials")

    logger.info("[MAIN] Process staying alive 24/7 for dashboard + market loops")
    while True:
        time.sleep(60)


if __name__ == "__main__":
    setup_logging()
    logger.info("Starting AI Quant Bot (24/7 dual market)...")
    try:
        run_bot()
    except KeyboardInterrupt:
        logger.info("\nBot stopped by user (Ctrl+C).")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
