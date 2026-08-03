"""
dashboard_server.py — Unified Web Admin Dashboard Backend
=============================================================
Provides REST API and Web Interface for both US (Alpaca) and
India (Angel One) trading bots.

Supports:
  - US market endpoints (existing)
  - India market endpoints (new)
  - Combined market view
  - Cloud deployment (Render, Heroku) via PORT env var
"""

import logging
import os
import time
from datetime import datetime, timezone
import threading

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

import config
from data_feed import DataFeed
from strategy import Strategy, create_strategy
from risk_manager import RiskManager
from execution import TradeExecutor
import trade_journal
import bot_state
import alerts

logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# US components
_executor = None
_data_feed = None
_strategy = None
_risk_mgr = None
_equity_history = []

# India components
_india_broker = None
_india_strategy = None
_india_risk_mgr = None
_india_equity_history = []

# Scanner response cache — dashboard used to re-hit Alpaca every few seconds
SCANNER_CACHE_TTL_SEC = 90.0
_us_scanner_cache: tuple[float, list] | None = None
_india_scanner_cache: tuple[float, list] | None = None
_us_scanner_lock = threading.Lock()
_india_scanner_lock = threading.Lock()


def get_components():
    """Initialize US market components (Alpaca paper/live)."""
    global _executor, _data_feed, _strategy, _risk_mgr
    if config.IS_PLACEHOLDER_KEY:
        if _risk_mgr is None:
            _risk_mgr = RiskManager(market="US")
        if _strategy is None:
            _strategy = create_strategy("US")
        return None, None, _strategy, _risk_mgr

    if _executor is None:
        try:
            _executor = TradeExecutor()
            _data_feed = DataFeed()
            _strategy = create_strategy("US")
            _risk_mgr = RiskManager(market="US")
        except Exception as e:
            logger.error(f"Error initializing US dashboard components: {e}")
    return _executor, _data_feed, _strategy, _risk_mgr


def get_india_components():
    """Initialize India market components (Angel One)."""
    global _india_broker, _india_strategy, _india_risk_mgr
    if not config.INDIA_ENABLED:
        return None, None

    if _india_broker is None:
        try:
            from india_broker import IndiaBroker
            _india_broker = IndiaBroker()
            _india_strategy = create_strategy("INDIA")
            _india_risk_mgr = RiskManager(market="INDIA")
        except Exception as e:
            logger.error(f"Error initializing India dashboard components: {e}")
    return _india_broker, _india_strategy


def get_india_risk():
    global _india_risk_mgr
    if _india_risk_mgr is None:
        _india_risk_mgr = RiskManager(market="INDIA")
    return _india_risk_mgr


# ===========================================================================
# Web Page Route
# ===========================================================================
@app.route("/")
def index():
    return render_template("index.html")


# ===========================================================================
# US Market API Endpoints (Existing)
# ===========================================================================
@app.route("/api/status")
def get_status():
    """US market status (Alpaca paper by default)."""
    executor, _, _, risk_mgr = get_components()
    account_info = executor.get_account_info() if executor else None

    if not account_info:
        return jsonify({
            "status": "error",
            "message": "Unable to connect to Alpaca. Check ALPACA_* keys (use Paper Trading keys).",
            "india_enabled": config.INDIA_ENABLED,
            "india_paper": config.INDIA_PAPER,
            "live_armed": config.LIVE_CONFIRMED,
        }), 500

    current_equity = account_info["equity"]
    last_equity = account_info["last_equity"]
    daily_pl = current_equity - last_equity
    daily_pl_pct = (daily_pl / last_equity * 100) if last_equity > 0 else 0.0

    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
    if not _equity_history or _equity_history[-1]["timestamp"] != now_str:
        _equity_history.append({"timestamp": now_str, "equity": round(current_equity, 2)})
        if len(_equity_history) > 60:
            _equity_history.pop(0)

    return jsonify({
        "status": "success",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "market": "US",
        "currency": "USD",
        "paper_trading": config.PAPER_TRADING,
        "live_armed": config.LIVE_CONFIRMED,
        "strategy": config.STRATEGY_NAME,
        "equity": current_equity,
        "last_equity": last_equity,
        "buying_power": account_info["buying_power"],
        "cash": account_info["cash"],
        "daily_pl": round(daily_pl, 2),
        "daily_pl_pct": round(daily_pl_pct, 2),
        "kill_switch_active": risk_mgr.is_kill_switch_active if risk_mgr else False,
        "market_open": _is_us_market_open_simple(),
        "india_enabled": config.INDIA_ENABLED,
        "india_paper": config.INDIA_PAPER,
        "equity_history": _equity_history,
        "performance": trade_journal.performance_stats("US"),
        "open_risk_pct": round(
            risk_mgr.open_risk_pct(current_equity, executor.get_open_positions() if executor else {})
            if risk_mgr else 0.0,
            4,
        ),
    })


def _is_us_market_open_simple() -> bool:
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.now()
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return (9 * 60 + 30) <= minutes <= (16 * 60)


def _is_india_market_open_simple() -> bool:
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        now = datetime.now()
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return (9 * 60 + 15) <= minutes <= (15 * 60 + 30)


@app.route("/api/positions")
def get_positions():
    executor, _, _, risk_mgr = get_components()
    if not executor:
        return jsonify([])

    positions_dict = executor.get_open_positions()
    positions_list = []

    for symbol, pos in positions_dict.items():
        entry_price = pos["avg_entry_price"]
        atr = None
        sl_price = pos.get("stop_loss")
        tp_price = pos.get("take_profit")
        if sl_price is None:
            sl_price = risk_mgr.get_stop_loss_price(entry_price, atr) if risk_mgr else round(entry_price * 0.98, 2)
        if tp_price is None:
            tp_price = (
                risk_mgr.get_take_profit_price(entry_price, stop_loss_price=sl_price, atr=atr)
                if risk_mgr
                else round(entry_price * 1.04, 2)
            )

        positions_list.append({
            "symbol": symbol,
            "qty": pos["qty"],
            "avg_entry_price": entry_price,
            "current_price": pos["current_price"],
            "market_value": pos["market_value"],
            "unrealized_pl": pos["unrealized_pl"],
            "unrealized_plpc": round(pos["unrealized_plpc"] * 100, 2),
            "stop_loss": sl_price,
            "take_profit": tp_price
        })

    return jsonify(positions_list)


@app.route("/api/scanner")
def get_scanner():
    global _us_scanner_cache

    cached_signals = bot_state.get_signals("US", max_age_sec=max(600, config.LOOP_INTERVAL_SEC * 3))
    if cached_signals:
        return jsonify([
            {
                "symbol": s["symbol"],
                "price": s.get("price") or 0.0,
                "rsi": s.get("rsi"),
                "adx": s.get("adx"),
                "signal": s.get("signal", "HOLD"),
                "reason": s.get("reason", ""),
                "strategy": s.get("strategy"),
                "source": "bot_cache",
            }
            for s in cached_signals
        ])

    now = time.time()
    if _us_scanner_cache and (now - _us_scanner_cache[0]) < SCANNER_CACHE_TTL_SEC:
        return jsonify(_us_scanner_cache[1])

    with _us_scanner_lock:
        now = time.time()
        if _us_scanner_cache and (now - _us_scanner_cache[0]) < SCANNER_CACHE_TTL_SEC:
            return jsonify(_us_scanner_cache[1])

        _, data_feed, strategy, _ = get_components()
        if not data_feed or not strategy:
            return jsonify([])

        scanner_results = []
        sma_slow = getattr(strategy.p, "sma_slow", config.SMA_SLOW) if hasattr(strategy, "p") else config.SMA_SLOW
        sma_fast = getattr(strategy.p, "sma_fast", config.SMA_FAST) if hasattr(strategy, "p") else config.SMA_FAST
        rsi_period = getattr(strategy.p, "rsi_period", config.RSI_PERIOD) if hasattr(strategy, "p") else config.RSI_PERIOD

        for symbol in config.STOCK_UNIVERSE:
            try:
                df = data_feed.get_historical_bars(symbol)
                if df is not None and not df.empty:
                    df = strategy.compute_indicators(df)
                    signal = strategy.generate_signal(df, symbol)
                    latest = df.iloc[-1]

                    scanner_results.append({
                        "symbol": symbol,
                        "price": round(float(latest["close"]), 2),
                        "sma_200": round(float(latest[f"SMA_{sma_slow}"]), 2) if not pd_isna(latest.get(f"SMA_{sma_slow}")) else None,
                        "sma_20": round(float(latest[f"SMA_{sma_fast}"]), 2) if not pd_isna(latest.get(f"SMA_{sma_fast}")) else None,
                        "rsi": round(float(latest[f"RSI_{rsi_period}"]), 1) if not pd_isna(latest.get(f"RSI_{rsi_period}")) else None,
                        "bbl": round(float(latest["BBL"]), 2) if not pd_isna(latest.get("BBL")) else None,
                        "bbu": round(float(latest["BBU"]), 2) if not pd_isna(latest.get("BBU")) else None,
                        "atr": round(float(latest["ATR"]), 2) if not pd_isna(latest.get("ATR")) else None,
                        "adx": round(float(latest["ADX"]), 1) if not pd_isna(latest.get("ADX")) else None,
                        "signal": signal
                    })
                else:
                    scanner_results.append({
                        "symbol": symbol,
                        "price": 0.0,
                        "signal": "NO_DATA"
                    })
            except Exception as e:
                logger.error(f"Error scanning {symbol}: {e}")
                scanner_results.append({
                    "symbol": symbol,
                    "price": 0.0,
                    "signal": "ERROR"
                })

        _us_scanner_cache = (time.time(), scanner_results)
        return jsonify(scanner_results)


# ===========================================================================
# India Market API Endpoints (New)
# ===========================================================================
@app.route("/api/india/status")
def get_india_status():
    """Get India market account status from Angel One."""
    if not config.INDIA_ENABLED:
        return jsonify({
            "status": "disabled",
            "message": "India trading disabled. Add ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PIN, ANGEL_TOTP_SECRET to Render Environment Variables."
        })

    india_broker, _ = get_india_components()
    if not india_broker or not india_broker.is_logged_in:
        err_msg = india_broker.last_error if (india_broker and india_broker.last_error) else "Angel One authentication failed. Verify keys in Render Environment."
        return jsonify({
            "status": "error",
            "message": err_msg
        })

    account_info = india_broker.get_account_info()
    if not account_info:
        err_msg = india_broker.last_error if india_broker.last_error else "Unable to fetch Angel One account info."
        return jsonify({
            "status": "error",
            "message": err_msg
        })

    equity = account_info["equity"]
    cash = account_info["available_cash"]

    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
    if not _india_equity_history or _india_equity_history[-1]["timestamp"] != now_str:
        _india_equity_history.append({"timestamp": now_str, "equity": round(equity, 2)})
        if len(_india_equity_history) > 60:
            _india_equity_history.pop(0)

    try:
        from zoneinfo import ZoneInfo
        IST = ZoneInfo("Asia/Kolkata")
    except ImportError:
        import pytz
        IST = pytz.timezone("Asia/Kolkata")

    now_ist = datetime.now(IST)
    is_weekday = now_ist.weekday() < 5
    market_open_time = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close_time = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    india_market_open = is_weekday and market_open_time <= now_ist <= market_close_time

    india_risk = get_india_risk()
    sod = bot_state.india_sod_equity(equity)
    last_eq = float(account_info.get("last_equity") or sod)
    daily_pl = equity - last_eq
    daily_pl_pct = (daily_pl / last_eq * 100) if last_eq else 0.0
    return jsonify({
        "status": "success",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "equity": equity,
        "last_equity": last_eq,
        "daily_pl": round(daily_pl, 2),
        "daily_pl_pct": round(daily_pl_pct, 2),
        "available_cash": cash,
        "used_margin": account_info.get("used_margin", 0),
        "market_open": india_market_open,
        "logged_in": india_broker.is_logged_in,
        "paper_trading": config.INDIA_PAPER,
        "live_armed": config.LIVE_CONFIRMED,
        "strategy": config.STRATEGY_NAME,
        "kill_switch_active": india_risk.is_kill_switch_active,
        "equity_history": _india_equity_history,
        "performance": trade_journal.performance_stats("INDIA"),
        "open_risk_pct": round(
            india_risk.open_risk_pct(equity, india_broker.get_open_positions()),
            4,
        ),
    })


@app.route("/api/india/positions")
def get_india_positions():
    if not config.INDIA_ENABLED:
        return jsonify([])

    india_broker, _ = get_india_components()
    if not india_broker or not india_broker.is_logged_in:
        return jsonify([])

    positions_dict = india_broker.get_open_positions()
    positions_list = []

    risk_mgr = get_india_risk()

    for symbol, pos in positions_dict.items():
        entry_price = pos["avg_entry_price"]
        atr = pos.get("atr")
        sl_price = pos.get("stop_loss")
        tp_price = pos.get("take_profit")
        if sl_price is None:
            sl_price = risk_mgr.get_stop_loss_price(entry_price, atr)
        if tp_price is None:
            tp_price = risk_mgr.get_take_profit_price(
                entry_price, stop_loss_price=sl_price, atr=atr
            )

        positions_list.append({
            "symbol": symbol,
            "qty": pos["qty"],
            "avg_entry_price": entry_price,
            "current_price": pos["current_price"],
            "market_value": pos["market_value"],
            "unrealized_pl": pos["unrealized_pl"],
            "unrealized_plpc": round(pos["unrealized_plpc"] * 100, 2),
            "stop_loss": sl_price,
            "take_profit": tp_price
        })

    return jsonify(positions_list)


@app.route("/api/india/scanner")
def get_india_scanner():
    global _india_scanner_cache

    if not config.INDIA_ENABLED:
        return jsonify([])

    cached_signals = bot_state.get_signals("INDIA", max_age_sec=max(600, config.INDIA_LOOP_INTERVAL_SEC * 3))
    if cached_signals:
        return jsonify([
            {
                "symbol": s["symbol"],
                "price": s.get("price") or 0.0,
                "rsi": s.get("rsi"),
                "adx": s.get("adx"),
                "signal": s.get("signal", "HOLD"),
                "reason": s.get("reason", ""),
                "strategy": s.get("strategy"),
                "source": "bot_cache",
            }
            for s in cached_signals
        ])

    now = time.time()
    if _india_scanner_cache and (now - _india_scanner_cache[0]) < SCANNER_CACHE_TTL_SEC:
        return jsonify(_india_scanner_cache[1])

    with _india_scanner_lock:
        now = time.time()
        if _india_scanner_cache and (now - _india_scanner_cache[0]) < SCANNER_CACHE_TTL_SEC:
            return jsonify(_india_scanner_cache[1])

        india_broker, strategy = get_india_components()
        if not india_broker or not india_broker.is_logged_in or not strategy:
            return jsonify([])

        sma_slow = getattr(strategy.p, "sma_slow", config.INDIA_SMA_SLOW) if hasattr(strategy, "p") else config.INDIA_SMA_SLOW
        sma_fast = getattr(strategy.p, "sma_fast", config.INDIA_SMA_FAST) if hasattr(strategy, "p") else config.INDIA_SMA_FAST
        rsi_period = getattr(strategy.p, "rsi_period", config.INDIA_RSI_PERIOD) if hasattr(strategy, "p") else config.INDIA_RSI_PERIOD

        scanner_results = []
        for symbol in config.INDIA_STOCK_UNIVERSE:
            try:
                df = india_broker.get_historical_bars(symbol)
                if df is not None and not df.empty:
                    df = strategy.compute_indicators(df)
                    signal = strategy.generate_signal(df, symbol)
                    latest = df.iloc[-1]

                    scanner_results.append({
                        "symbol": symbol,
                        "price": round(float(latest["close"]), 2),
                        "sma_200": round(float(latest[f"SMA_{sma_slow}"]), 2) if not pd_isna(latest.get(f"SMA_{sma_slow}")) else None,
                        "sma_20": round(float(latest[f"SMA_{sma_fast}"]), 2) if not pd_isna(latest.get(f"SMA_{sma_fast}")) else None,
                        "rsi": round(float(latest[f"RSI_{rsi_period}"]), 1) if not pd_isna(latest.get(f"RSI_{rsi_period}")) else None,
                        "bbl": round(float(latest["BBL"]), 2) if not pd_isna(latest.get("BBL")) else None,
                        "bbu": round(float(latest["BBU"]), 2) if not pd_isna(latest.get("BBU")) else None,
                        "atr": round(float(latest["ATR"]), 2) if not pd_isna(latest.get("ATR")) else None,
                        "adx": round(float(latest["ADX"]), 1) if not pd_isna(latest.get("ADX")) else None,
                        "signal": signal
                    })
                else:
                    scanner_results.append({
                        "symbol": symbol,
                        "price": 0.0,
                        "signal": "NO_DATA"
                    })
            except Exception as e:
                logger.error(f"Error scanning India {symbol}: {e}")
                scanner_results.append({
                    "symbol": symbol,
                    "price": 0.0,
                    "signal": "ERROR"
                })

        _india_scanner_cache = (time.time(), scanner_results)
        return jsonify(scanner_results)


@app.route("/api/india/close_position/<symbol>", methods=["POST"])
def close_india_position(symbol):
    india_broker, _ = get_india_components()
    if not india_broker:
        return jsonify({"status": "error", "message": "India broker not available"}), 500

    success = india_broker.close_position(symbol)
    if success:
        return jsonify({"status": "success", "message": f"Closed India position for {symbol}"})
    else:
        return jsonify({"status": "error", "message": f"Failed to close India position for {symbol}"}), 400


# ===========================================================================
# Combined Market View
# ===========================================================================
@app.route("/api/combined/status")
def get_combined_status():
    result = {
        "us": None,
        "india": None,
        "combined_equity": 0,
        "india_enabled": config.INDIA_ENABLED,
        "us_paper": config.PAPER_TRADING,
        "india_paper": config.INDIA_PAPER,
        "live_armed": config.LIVE_CONFIRMED,
        "equity_history": [],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    us_equity = 0.0
    india_equity = 0.0

    executor, _, _, risk_mgr = get_components()
    if executor:
        us_account = executor.get_account_info()
        if us_account:
            us_equity = float(us_account["equity"])
            result["us"] = {
                "equity": us_account["equity"],
                "daily_pl": round(us_account["equity"] - us_account["last_equity"], 2),
                "cash": us_account["cash"],
            }
            result["combined_equity"] += us_equity
            now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
            if not _equity_history or _equity_history[-1]["timestamp"] != now_str:
                _equity_history.append({"timestamp": now_str, "equity": round(us_equity, 2)})
                if len(_equity_history) > 60:
                    _equity_history.pop(0)

    if config.INDIA_ENABLED:
        india_broker, _ = get_india_components()
        if india_broker and india_broker.is_logged_in:
            india_account = india_broker.get_account_info()
            if india_account:
                india_equity = float(india_account["equity"])
                result["india"] = {
                    "equity": india_account["equity"],
                    "available_cash": india_account["available_cash"],
                }
                result["combined_equity"] += india_equity
                now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
                if not _india_equity_history or _india_equity_history[-1]["timestamp"] != now_str:
                    _india_equity_history.append(
                        {"timestamp": now_str, "equity": round(india_equity, 2)}
                    )
                    if len(_india_equity_history) > 60:
                        _india_equity_history.pop(0)

    # Chart uses US equity history when available; else India
    result["equity_history"] = _equity_history or _india_equity_history
    return jsonify(result)


@app.route("/api/performance")
def get_performance():
    """Trade journal performance metrics (win rate, PF, max DD, open risk)."""
    market = request.args.get("market")
    if market:
        market = market.upper()
    stats = trade_journal.performance_stats(market)
    curve = trade_journal.equity_curve(market, limit=200)
    trades = trade_journal.recent_trades(limit=30, market=market)

    open_risk = 0.0
    if market == "US" or market is None:
        executor, _, _, risk_mgr = get_components()
        if executor and risk_mgr:
            acct = executor.get_account_info()
            if acct:
                open_risk = risk_mgr.open_risk_pct(acct["equity"], executor.get_open_positions())
    if market == "INDIA":
        india_broker, _ = get_india_components()
        if india_broker and india_broker.is_logged_in:
            acct = india_broker.get_account_info()
            if acct:
                open_risk = get_india_risk().open_risk_pct(
                    acct["equity"], india_broker.get_open_positions()
                )

    return jsonify({
        "status": "success",
        "market": market or "ALL",
        "strategy": config.STRATEGY_NAME,
        "stats": stats,
        "equity_curve": curve,
        "recent_trades": trades,
        "open_risk_pct": round(open_risk, 4),
    })


@app.route("/api/trades")
def get_trades():
    market = request.args.get("market")
    limit = int(request.args.get("limit", "50"))
    return jsonify(trade_journal.recent_trades(limit=limit, market=market))


def pd_isna(val):
    import pandas as pd
    return pd.isna(val)


@app.route("/api/logs")
def get_logs():
    # main.py writes to logs/trading_bot.log — keep paths in sync
    log_file = os.path.join("logs", "trading_bot.log")
    if not os.path.exists(log_file):
        return jsonify({"logs": ["Log file not created yet. Run the main bot to generate logs."]})

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return jsonify({"logs": [line.strip() for line in lines[-50:]]})
    except Exception as e:
        return jsonify({"logs": [f"Error reading log file: {e}"]})


@app.route("/api/close_position/<symbol>", methods=["POST"])
def close_position(symbol):
    executor, _, _, _ = get_components()
    if not executor:
        return jsonify({"status": "error", "message": "Executor not available"}), 500

    success = executor.close_position(symbol)
    if success:
        return jsonify({"status": "success", "message": f"Closed position for {symbol}"})
    else:
        return jsonify({"status": "error", "message": f"Failed to close position for {symbol}"}), 400


@app.route("/api/toggle_kill_switch", methods=["POST"])
def toggle_kill_switch():
    _, _, _, us_risk = get_components()
    india_risk = get_india_risk()
    if not us_risk and not india_risk:
        return jsonify({"status": "error", "message": "Risk manager not available"}), 500

    any_active = bool(
        (us_risk and us_risk.is_kill_switch_active)
        or (india_risk and india_risk.is_kill_switch_active)
    )
    if any_active:
        if us_risk:
            us_risk.reset_kill_switch()
        if india_risk:
            india_risk.reset_kill_switch()
        alerts.kill_switch_alert("ALL", False)
        state = "reset for US and India"
    else:
        if us_risk:
            us_risk.activate_kill_switch("dashboard")
        if india_risk:
            india_risk.activate_kill_switch("dashboard")
        alerts.kill_switch_alert("ALL", True)
        state = "activated for US and India"

    return jsonify({"status": "success", "message": f"Kill switch {state}"})


@app.route("/api/health")
def get_health():
    h = bot_state.get_health()
    us_risk = get_components()[3]
    india_risk = get_india_risk()
    h["us_kill_switch"] = bool(us_risk.is_kill_switch_active) if us_risk else False
    h["india_kill_switch"] = bool(india_risk.is_kill_switch_active) if india_risk else False
    h["us_enabled"] = config.US_ENABLED
    h["india_enabled"] = config.INDIA_ENABLED
    return jsonify(h)


@app.route("/api/equity_curves")
def get_equity_curves():
    return jsonify({
        "us": trade_journal.equity_curve("US", limit=120),
        "india": trade_journal.equity_curve("INDIA", limit=120),
    })


def run_dashboard_server(host="0.0.0.0", port=None):
    if port is None:
        port = int(os.environ.get("PORT", 8080))
    logger.info(f"Admin Dashboard running on port {port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)


def start_dashboard_in_background(port=None):
    if port is None:
        port = int(os.environ.get("PORT", 8080))
    t = threading.Thread(target=run_dashboard_server, kwargs={"port": port}, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_dashboard_server()
