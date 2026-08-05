"""
dashboard_server.py — Web Admin Dashboard Backend
=============================================================
Provides REST API and Web Interface for India (Dhan/Angel) and US (Dhan Global) trading bot.

Supports:
  - India and US market endpoints (/api/status vs /api/us/status, etc.)
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
from strategy import Strategy, create_strategy
from risk_manager import RiskManager
import trade_journal
import bot_state
import alerts

logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# India components
_india_broker = None
_india_strategy = None
_india_risk_mgr = None
_india_equity_history = []

SCANNER_CACHE_TTL_SEC = 90.0
_india_scanner_cache: tuple[float, list] | None = None
_india_scanner_lock = threading.Lock()

# US components
_us_broker = None
_us_strategy = None
_us_risk_mgr = None
_us_equity_history = []
_us_scanner_cache: tuple[float, list] | None = None
_us_scanner_lock = threading.Lock()


def get_india_components():
    """Initialize India market components — shared broker singleton."""
    global _india_broker, _india_strategy, _india_risk_mgr
    if not config.INDIA_ENABLED:
        return None, None

    if _india_broker is None:
        try:
            from india_client import get_shared_india_broker
            _india_broker = get_shared_india_broker(auto_login=True)
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


def get_us_components():
    """Initialize US market components — shared broker singleton."""
    global _us_broker, _us_strategy, _us_risk_mgr
    if not config.US_ENABLED:
        return None, None

    if _us_broker is None:
        try:
            from us_client import get_shared_us_broker
            _us_broker = get_shared_us_broker(auto_login=True)
            _us_strategy = create_strategy("US")
            _us_risk_mgr = RiskManager(market="US")
        except Exception as e:
            logger.error(f"Error initializing US dashboard components: {e}")
    return _us_broker, _us_strategy


def get_us_risk():
    global _us_risk_mgr
    if _us_risk_mgr is None:
        _us_risk_mgr = RiskManager(market="US")
    return _us_risk_mgr


# ===========================================================================
# Web Page Route
# ===========================================================================
@app.route("/")
def index():
    return render_template("index.html")


# ===========================================================================
# India API Endpoints
# ===========================================================================
@app.route("/api/status")
def get_india_status():
    """Get India market account status."""
    if not config.INDIA_ENABLED:
        return jsonify({
            "status": "disabled",
            "message": "India trading disabled. Add ANGEL_* or DHAN_* keys to environment."
        })

    india_broker, _ = get_india_components()
    if not india_broker or not india_broker.is_logged_in:
        err_msg = (
            india_broker.last_error
            if (india_broker and india_broker.last_error)
            else f"{config.INDIA_BROKER} authentication failed. Verify credentials."
        )
        return jsonify({
            "status": "error",
            "message": err_msg
        })

    account_info = india_broker.get_account_info()
    if not account_info:
        err_msg = (
            india_broker.last_error
            if india_broker.last_error
            else f"Unable to fetch {config.INDIA_BROKER} account info."
        )
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
        "market": "INDIA",
        "currency": "INR",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "equity": equity,
        "last_equity": last_eq,
        "daily_pl": round(daily_pl, 2),
        "daily_pl_pct": round(daily_pl_pct, 2),
        "available_cash": cash,
        "used_margin": account_info.get("used_margin", 0),
        "market_open": india_market_open,
        "logged_in": india_broker.is_logged_in,
        "broker": config.INDIA_BROKER,
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


@app.route("/api/positions")
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


@app.route("/api/scanner")
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


@app.route("/api/close_position/<symbol>", methods=["POST"])
def close_india_position(symbol):
    india_broker, _ = get_india_components()
    if not india_broker:
        return jsonify({"status": "error", "message": "India broker not available"}), 500

    success = india_broker.close_position(symbol)
    if success:
        return jsonify({"status": "success", "message": f"Closed India position for {symbol}"})
    else:
        return jsonify({"status": "error", "message": f"Failed to close India position for {symbol}"}), 400


@app.route("/api/toggle_kill_switch", methods=["POST"])
def toggle_india_kill_switch():
    india_risk = get_india_risk()
    if not india_risk:
        return jsonify({"status": "error", "message": "Risk manager not available"}), 500

    if india_risk.is_kill_switch_active:
        india_risk.reset_kill_switch()
        alerts.kill_switch_alert("INDIA", False)
        state = "reset"
    else:
        india_risk.activate_kill_switch("dashboard")
        alerts.kill_switch_alert("INDIA", True)
        state = "activated"

    return jsonify({"status": "success", "message": f"India kill switch {state}"})


# ===========================================================================
# US API Endpoints
# ===========================================================================
@app.route("/api/us/status")
def get_us_status():
    """Get US market account status."""
    if not config.US_ENABLED:
        return jsonify({
            "status": "disabled",
            "message": "US trading disabled. Set DHAN_* and US_PAPER=true or US_LIVE_TRADING=true."
        })

    us_broker, _ = get_us_components()
    if not us_broker or not us_broker.is_logged_in:
        err_msg = (
            us_broker.last_error
            if (us_broker and us_broker.last_error)
            else "Dhan Global authentication failed."
        )
        return jsonify({
            "status": "error",
            "message": err_msg
        })

    account_info = us_broker.get_account_info()
    if not account_info:
        err_msg = (
            us_broker.last_error
            if us_broker.last_error
            else "Unable to fetch Dhan Global account info."
        )
        return jsonify({
            "status": "error",
            "message": err_msg
        })

    equity = account_info["equity"]
    cash = account_info["available_cash"]

    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
    if not _us_equity_history or _us_equity_history[-1]["timestamp"] != now_str:
        _us_equity_history.append({"timestamp": now_str, "equity": round(equity, 2)})
        if len(_us_equity_history) > 60:
            _us_equity_history.pop(0)

    us_market_open = us_broker.is_market_open()
    us_risk = get_us_risk()
    sod = bot_state.us_sod_equity(equity)
    last_eq = float(account_info.get("last_equity") or sod)
    daily_pl = equity - last_eq
    daily_pl_pct = (daily_pl / last_eq * 100) if last_eq else 0.0

    return jsonify({
        "status": "success",
        "market": "US",
        "currency": "USD",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "equity": equity,
        "last_equity": last_eq,
        "daily_pl": round(daily_pl, 2),
        "daily_pl_pct": round(daily_pl_pct, 2),
        "available_cash": cash,
        "buying_power": account_info.get("buying_power", cash),
        "used_margin": account_info.get("used_margin", 0),
        "market_open": us_market_open,
        "logged_in": us_broker.is_logged_in,
        "broker": "dhan_global",
        "paper_trading": config.US_PAPER,
        "live_armed": config.US_LIVE_CONFIRMED,
        "global_activated": us_broker.global_stocks_available,
        "strategy": config.STRATEGY_NAME,
        "kill_switch_active": us_risk.is_kill_switch_active,
        "equity_history": _us_equity_history,
        "performance": trade_journal.performance_stats("US"),
        "open_risk_pct": round(
            us_risk.open_risk_pct(equity, us_broker.get_open_positions()),
            4,
        ),
    })


@app.route("/api/us/positions")
def get_us_positions():
    if not config.US_ENABLED:
        return jsonify([])

    us_broker, _ = get_us_components()
    if not us_broker or not us_broker.is_logged_in:
        return jsonify([])

    positions_dict = us_broker.get_open_positions()
    positions_list = []

    risk_mgr = get_us_risk()

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


@app.route("/api/us/scanner")
def get_us_scanner():
    global _us_scanner_cache

    if not config.US_ENABLED:
        return jsonify([])

    cached_signals = bot_state.get_signals("US", max_age_sec=max(600, config.US_LOOP_INTERVAL_SEC * 3))
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

        us_broker, strategy = get_us_components()
        if not us_broker or not us_broker.is_logged_in or not strategy:
            return jsonify([])

        sma_slow = getattr(strategy.p, "sma_slow", config.US_SMA_SLOW) if hasattr(strategy, "p") else config.US_SMA_SLOW
        sma_fast = getattr(strategy.p, "sma_fast", config.US_SMA_FAST) if hasattr(strategy, "p") else config.US_SMA_FAST
        rsi_period = getattr(strategy.p, "rsi_period", config.US_RSI_PERIOD) if hasattr(strategy, "p") else config.US_RSI_PERIOD

        scanner_results = []
        for symbol in config.US_STOCK_UNIVERSE:
            try:
                df = us_broker.get_historical_bars(symbol)
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
                logger.error(f"Error scanning US {symbol}: {e}")
                scanner_results.append({
                    "symbol": symbol,
                    "price": 0.0,
                    "signal": "ERROR"
                })

        _us_scanner_cache = (time.time(), scanner_results)
        return jsonify(scanner_results)


@app.route("/api/us/buy", methods=["POST"])
def buy_us_stock():
    """Manual buy trigger for US stock."""
    if not config.US_ENABLED:
        return jsonify({"status": "error", "message": "US trading disabled"}), 400

    us_broker, strategy = get_us_components()
    if not us_broker:
        return jsonify({"status": "error", "message": "US broker unavailable"}), 500

    data = request.get_json() or {}
    symbol = (data.get("symbol") or "").strip().upper()
    qty_in = data.get("qty")

    if not symbol:
        return jsonify({"status": "error", "message": "Missing symbol"}), 400

    if symbol not in config.US_STOCK_UNIVERSE:
        return jsonify({"status": "error", "message": f"{symbol} not in US universe"}), 400

    us_risk = get_us_risk()
    if us_risk.is_kill_switch_active:
        return jsonify({"status": "error", "message": "US kill switch is ACTIVE — buy blocked"}), 400

    account = us_broker.get_account_info()
    if not account:
        return jsonify({"status": "error", "message": "Cannot fetch US account info"}), 500

    quote = us_broker.get_latest_quote(symbol)
    price = float(quote["ltp"]) if (quote and quote.get("ltp")) else 0.0
    if price <= 0:
        return jsonify({"status": "error", "message": f"No valid price quote for {symbol}"}), 400

    df = us_broker.get_historical_bars(symbol)
    atr = None
    if df is not None and not df.empty and strategy:
        df = strategy.compute_indicators(df)
        atr = strategy.latest_atr(df)

    sl = us_risk.get_stop_loss_price(price, atr)
    tp = us_risk.get_take_profit_price(price, stop_loss_price=sl, atr=atr)

    if qty_in is not None:
        try:
            qty = int(qty_in)
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid qty"}), 400
    else:
        stop_dist = price - sl
        qty = us_risk.calculate_position_size(account["equity"], price, stop_distance=stop_dist)

    if qty <= 0:
        return jsonify({"status": "error", "message": "Position sizing calculated 0 shares"}), 400

    order_id = us_broker.place_buy_order(
        symbol=symbol,
        qty=qty,
        limit_price=price,
        stop_loss_price=sl,
        take_profit_price=tp,
        atr=atr,
    )

    if order_id:
        us_risk.register_trade(symbol, price, sl, atr)
        trade_journal.record_entry(
            "US", symbol, qty, price,
            stop_price=sl, take_profit=tp,
            reason="manual_dashboard_buy",
            strategy=strategy.name if strategy else "manual",
            meta={"atr": atr, "order_id": order_id},
        )
        alerts.trade_alert("US", "BUY", symbol, f"qty={qty} @${price:.2f} (manual)")
        return jsonify({
            "status": "success",
            "message": f"BUY order placed for {qty} shares of {symbol} @ ${price:.2f} (ID: {order_id})",
            "order_id": order_id
        })
    else:
        return jsonify({
            "status": "error",
            "message": us_broker.last_error or f"Failed to place BUY order for {symbol}"
        }), 400


@app.route("/api/us/close_position/<symbol>", methods=["POST"])
def close_us_position(symbol):
    us_broker, _ = get_us_components()
    if not us_broker:
        return jsonify({"status": "error", "message": "US broker not available"}), 500

    success = us_broker.close_position(symbol)
    if success:
        return jsonify({"status": "success", "message": f"Closed US position for {symbol}"})
    else:
        return jsonify({"status": "error", "message": f"Failed to close US position for {symbol}"}), 400


@app.route("/api/us/toggle_kill_switch", methods=["POST"])
def toggle_us_kill_switch():
    us_risk = get_us_risk()
    if not us_risk:
        return jsonify({"status": "error", "message": "Risk manager not available"}), 500

    if us_risk.is_kill_switch_active:
        us_risk.reset_kill_switch()
        alerts.kill_switch_alert("US", False)
        state = "reset"
    else:
        us_risk.activate_kill_switch("dashboard")
        alerts.kill_switch_alert("US", True)
        state = "activated"

    return jsonify({"status": "success", "message": f"US kill switch {state}"})


# ===========================================================================
# General API Endpoints
# ===========================================================================
@app.route("/api/performance")
def get_performance():
    """Trade journal performance metrics (win rate, PF, max DD, open risk)."""
    market = request.args.get("market", "INDIA").upper()
    stats = trade_journal.performance_stats(market)
    curve = trade_journal.equity_curve(market, limit=200)
    trades = trade_journal.recent_trades(limit=30, market=market)

    open_risk = 0.0
    if market == "US":
        us_broker, _ = get_us_components()
        if us_broker and us_broker.is_logged_in:
            acct = us_broker.get_account_info()
            if acct:
                open_risk = get_us_risk().open_risk_pct(
                    acct["equity"], us_broker.get_open_positions()
                )
    else:
        india_broker, _ = get_india_components()
        if india_broker and india_broker.is_logged_in:
            acct = india_broker.get_account_info()
            if acct:
                open_risk = get_india_risk().open_risk_pct(
                    acct["equity"], india_broker.get_open_positions()
                )

    return jsonify({
        "status": "success",
        "market": market,
        "strategy": config.STRATEGY_NAME,
        "stats": stats,
        "equity_curve": curve,
        "recent_trades": trades,
        "open_risk_pct": round(open_risk, 4),
    })


@app.route("/api/trades")
def get_trades():
    market = request.args.get("market", "INDIA").upper()
    limit = int(request.args.get("limit", "50"))
    return jsonify(trade_journal.recent_trades(limit=limit, market=market))


def pd_isna(val):
    import pandas as pd
    return pd.isna(val)


@app.route("/api/logs")
def get_logs():
    log_file = os.path.join("logs", "trading_bot.log")
    if not os.path.exists(log_file):
        return jsonify({"logs": ["Log file not created yet. Run the main bot to generate logs."]})

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return jsonify({"logs": [line.strip() for line in lines[-50:]]})
    except Exception as e:
        return jsonify({"logs": [f"Error reading log file: {e}"]})


@app.route("/api/health")
def get_health():
    h = bot_state.get_health()
    india_risk = get_india_risk()
    us_risk = get_us_risk()
    h["india_kill_switch"] = bool(india_risk.is_kill_switch_active) if india_risk else False
    h["us_kill_switch"] = bool(us_risk.is_kill_switch_active) if us_risk else False
    h["india_enabled"] = config.INDIA_ENABLED
    h["us_enabled"] = config.US_ENABLED
    return jsonify(h)


@app.route("/api/equity_curves")
def get_equity_curves():
    return jsonify({
        "india": trade_journal.equity_curve("INDIA", limit=120),
        "us": trade_journal.equity_curve("US", limit=120),
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
