"""
main.py — Main Orchestrator & Web Admin Dashboard Launcher
===========================================================
24/7 India-only bot:
  India → Dhan (default) or Angel One — paper sim / live INR

Dashboard stays alive around the clock; trades only during market hours.
"""

import logging
import os
import sys
import time
import threading
from datetime import datetime

import config
from strategy import create_strategy, RelativeStrengthFilter
from risk_manager import RiskManager
from dashboard_server import start_dashboard_in_background
import trade_journal
import bot_state
import alerts
from filters import regime_allows, mtf_allows, fetch_daily_bars
from strategy import snapshot_signal

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except ImportError:
    import pytz  # type: ignore
    IST = pytz.timezone("Asia/Kolkata")


def setup_logging():
    from pathlib import Path

    log_format = "%(asctime)s | %(levelname)-8s | %(name)-18s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    root_logger.addHandler(console_handler)

    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "trading_bot.log", mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))
    root_logger.addHandler(file_handler)


logger = logging.getLogger("main")


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

def is_india_market_open() -> bool:
    """Returns True if current time is between Mon-Fri 9:15 AM - 3:30 PM IST."""
    now_ist = datetime.now(IST)
    if now_ist.weekday() >= 5:
        return False
    
    open_time = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    close_time = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    return open_time <= now_ist <= close_time


def run_india_loop(strategy, risk_mgr, rs_filter=None):
    from india_client import get_shared_india_broker

    logger.info("[INDIA] India Market trading loop starting (24/7 process)...")

    try:
        india_broker = get_shared_india_broker(auto_login=True)
    except Exception as e:
        logger.error(f"[INDIA] Failed to initialize India broker: {e}")
        return

    if not india_broker.is_logged_in:
        logger.error(
            f"[INDIA] Login failed: {india_broker.last_error}. "
            "Will keep process alive and retry after cooldown "
            "(do not restart the container repeatedly)."
        )
        # Do not exit — cooldown + ensure_session will retry later
    else:
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
                    # Single attempt; login() no-ops during cooldown
                    india_broker.login()
                time.sleep(config.INDIA_LOOP_INTERVAL_SEC)
                continue

            if not india_broker.is_logged_in:
                india_broker.ensure_session()
                if not india_broker.is_logged_in:
                    logger.warning(
                        f"[INDIA] Not logged in ({india_broker.last_error}) — "
                        f"skipping cycle"
                    )
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
                sod = bot_state.india_sod_equity(current_equity)
                start_of_day_equity = sod
            else:
                start_of_day_equity = sod
                bot_state.india_sod_equity(sod)

            trade_journal.snapshot_equity("INDIA", current_equity)

            if risk_mgr.check_daily_drawdown(current_equity, start_of_day_equity):
                logger.critical("[INDIA KILL-SWITCH] Trading PAUSED (daily drawdown).")
                alerts.kill_switch_alert("INDIA", True)
                india_broker.cancel_all_open_orders()
                time.sleep(config.INDIA_LOOP_INTERVAL_SEC)
                continue

            if risk_mgr.is_kill_switch_active:
                logger.critical("[INDIA KILL-SWITCH] Active — skipping entries.")
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

            regime_ok = regime_allows("INDIA", bar_cache)
            signal_rows = []

            for symbol in config.INDIA_STOCK_UNIVERSE:
                logger.info(f"[INDIA] -- Scanning {symbol} " + "-" * (40 - len(symbol)))

                df = bar_cache.get(symbol)
                if df is None or df.empty:
                    logger.warning(f"[INDIA] {symbol}: No data — skipping.")
                    continue

                snap = snapshot_signal(strategy, df, symbol)
                signal_rows.append(snap)
                signal = snap["signal"]
                atr = strategy.latest_atr(df)

                if signal == "BUY":
                    if not tradable_window:
                        logger.info(f"{symbol}: BUY skipped — outside tradable session window")
                        continue
                    if not regime_ok:
                        logger.info(f"{symbol}: BUY skipped — regime filter blocked entries")
                        continue
                    if not risk_mgr.is_position_allowed(symbol, current_positions):
                        continue

                    quote = india_broker.get_latest_quote(symbol)
                    # Candle close already used for the signal — safe paper/live fallback
                    # when Dhan marketfeed LTP is down / not subscribed.
                    limit_price = None
                    if quote and quote.get("ltp"):
                        limit_price = float(quote["ltp"])
                    elif snap.get("price"):
                        limit_price = float(snap["price"])
                        logger.warning(
                            f"{symbol}: no live LTP — using signal candle close "
                            f"{limit_price:.2f} for entry"
                        )
                    if limit_price is None or limit_price <= 0:
                        logger.warning(f"{symbol}: BUY skipped — no usable price")
                        continue

                    sizing_equity = min(
                        current_equity,
                        float(account.get("available_cash") or current_equity),
                    )

                    sl = risk_mgr.get_stop_loss_price(limit_price, atr)
                    tp = risk_mgr.get_take_profit_price(
                        limit_price, stop_loss_price=sl, atr=atr
                    )
                    stop_dist = limit_price - sl
                    qty = risk_mgr.calculate_position_size(
                        sizing_equity, limit_price, stop_distance=stop_dist
                    )
                    if qty <= 0:
                        logger.warning(
                            f"{symbol}: BUY skipped — sized to 0 shares "
                            f"(price={limit_price:.2f}, equity={sizing_equity:.0f})"
                        )
                        continue

                    order_id = india_broker.place_buy_order(
                        symbol=symbol,
                        qty=qty,
                        limit_price=limit_price,
                        stop_loss_price=sl,
                        take_profit_price=tp,
                        atr=atr,
                    )
                    if not order_id:
                        logger.warning(
                            f"{symbol}: BUY order failed — "
                            f"{getattr(india_broker, 'last_error', 'unknown')}"
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
                        alerts.trade_alert("INDIA", "BUY", symbol, f"qty={qty} @{limit_price}")
                        current_positions[symbol] = {"qty": qty}

                elif signal == "SELL" and symbol in current_positions:
                    pos = current_positions[symbol]
                    px = pos.get("current_price") or pos.get("avg_entry_price")
                    if india_broker.close_position(symbol):
                        trade_journal.record_exit(
                            "INDIA", symbol, float(px), reason="signal_sell"
                        )
                        risk_mgr.clear_trade(symbol)
                        alerts.trade_alert("INDIA", "SELL", symbol, f"@{px}")

            bot_state.publish_signals("INDIA", signal_rows)
            bot_state.mark_healthy("INDIA")
            log_india_portfolio_summary(india_broker, "INDIA")

            elapsed = time.time() - loop_start
            sleep_time = max(0, config.INDIA_LOOP_INTERVAL_SEC - elapsed)
            logger.info(f"[INDIA COMPLETE] Cycle done ({elapsed:.1f}s). Next in {sleep_time:.0f}s.\n")
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"[INDIA ERROR] {e}", exc_info=True)
            bot_state.mark_cycle("INDIA", error=str(e))
            alerts.health_alert(f"INDIA loop error: {e}")
            time.sleep(config.INDIA_LOOP_INTERVAL_SEC)


def run_bot():
    logger.info("=" * 70)
    logger.info("   AI QUANT BOT — INDIA ONLY")
    logger.info(
        f"   India: enabled={config.INDIA_ENABLED} | broker={config.INDIA_BROKER} | "
        f"paper_sim={config.INDIA_PAPER} | live_armed={config.LIVE_CONFIRMED}"
    )
    logger.info(
        f"   Strategy={config.STRATEGY_NAME} | RS={config.USE_RELATIVE_STRENGTH} | "
        f"Risk/trade={config.RISK_PER_TRADE:.2%} | ATR_SL={config.ATR_STOP_MULT}x | "
        f"TP={config.TAKE_PROFIT_R}R | MaxOpen={config.MAX_OPEN_POSITIONS}"
    )
    logger.info("=" * 70)

    if not config.INDIA_ENABLED:
        logger.critical(
            "No markets configured. Add Dhan (DHAN_*) keys to .env"
        )
        return

    if config.LIVE_CONFIRMED:
        logger.critical("!!! INDIA REAL MONEY MODE ARMED !!!")
    elif config.INDIA_PAPER:
        logger.info("India PAPER SIM on — live NSE data, fake INR (safe for testing)")

    trade_journal.init_db()

    try:
        dash_port = int(os.environ.get("PORT", 5000))
        start_dashboard_in_background(port=dash_port)
        logger.info(f"[DASHBOARD] http://0.0.0.0:{dash_port}")
    except Exception as e:
        logger.warning(f"Dashboard failed to start: {e}")

    india_rs = RelativeStrengthFilter() if config.USE_RELATIVE_STRENGTH else None
    india_strategy = create_strategy("INDIA", rs_filter=india_rs)
    india_risk = RiskManager(market="INDIA")

    if config.INDIA_ENABLED:
        india_thread = threading.Thread(
            target=run_india_loop,
            args=(india_strategy, india_risk, india_rs),
            daemon=True,
            name="IndiaMarketLoop",
        )
        india_thread.start()
        logger.info(
            f"[INDIA] Background loop started ({config.INDIA_BROKER} + paper/live)"
        )
    else:
        logger.warning(
            "[INDIA] Disabled — missing Dhan/Angel credentials "
            f"(INDIA_BROKER={config.INDIA_BROKER})"
        )

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
