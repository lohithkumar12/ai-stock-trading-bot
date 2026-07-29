"""
dashboard_server.py — Web Admin Dashboard Backend
===================================================
Provides a REST API and Web Interface to view real-time trading stats,
portfolio equity, P&L, active positions, strategy signals, and bot logs.

Supports cloud deployment (Render, Heroku) by reading PORT from env.
"""

import logging
import os
from datetime import datetime, timezone
import threading

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

import config
from data_feed import DataFeed
from strategy import Strategy
from risk_manager import RiskManager
from execution import TradeExecutor

logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

_executor = None
_data_feed = None
_strategy = None
_risk_mgr = None
_equity_history = []


def get_components():
    global _executor, _data_feed, _strategy, _risk_mgr
    if _executor is None:
        try:
            _executor = TradeExecutor()
            _data_feed = DataFeed()
            _strategy = Strategy()
            _risk_mgr = RiskManager()
        except Exception as e:
            logger.error(f"Error initializing dashboard components: {e}")
    return _executor, _data_feed, _strategy, _risk_mgr


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def get_status():
    executor, _, _, risk_mgr = get_components()
    account_info = executor.get_account_info() if executor else None

    if not account_info:
        return jsonify({
            "status": "error",
            "message": "Unable to connect to Alpaca Account. Please verify your .env credentials."
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

    now = datetime.now()
    is_weekday = now.weekday() < 5
    is_hours = 9 <= now.hour < 16 or (now.hour == 16 and now.minute == 0)
    market_open = is_weekday and is_hours

    return jsonify({
        "status": "success",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "paper_trading": config.PAPER_TRADING,
        "equity": current_equity,
        "last_equity": last_equity,
        "buying_power": account_info["buying_power"],
        "cash": account_info["cash"],
        "daily_pl": round(daily_pl, 2),
        "daily_pl_pct": round(daily_pl_pct, 2),
        "kill_switch_active": risk_mgr.is_kill_switch_active if risk_mgr else False,
        "market_open": market_open,
        "equity_history": _equity_history
    })


@app.route("/api/positions")
def get_positions():
    executor, _, _, risk_mgr = get_components()
    if not executor:
        return jsonify([])

    positions_dict = executor.get_open_positions()
    positions_list = []

    for symbol, pos in positions_dict.items():
        entry_price = pos["avg_entry_price"]
        sl_price = risk_mgr.get_stop_loss_price(entry_price) if risk_mgr else round(entry_price * 0.98, 2)
        tp_price = risk_mgr.get_take_profit_price(entry_price) if risk_mgr else round(entry_price * 1.04, 2)

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
    _, data_feed, strategy, _ = get_components()
    if not data_feed or not strategy:
        return jsonify([])

    scanner_results = []
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
                    "sma_200": round(float(latest[f"SMA_{config.SMA_SLOW}"]), 2) if not pd_isna(latest.get(f"SMA_{config.SMA_SLOW}")) else None,
                    "sma_20": round(float(latest[f"SMA_{config.SMA_FAST}"]), 2) if not pd_isna(latest.get(f"SMA_{config.SMA_FAST}")) else None,
                    "rsi": round(float(latest[f"RSI_{config.RSI_PERIOD}"]), 1) if not pd_isna(latest.get(f"RSI_{config.RSI_PERIOD}")) else None,
                    "bbl": round(float(latest["BBL"]), 2) if not pd_isna(latest.get("BBL")) else None,
                    "bbu": round(float(latest["BBU"]), 2) if not pd_isna(latest.get("BBU")) else None,
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

    return jsonify(scanner_results)


def pd_isna(val):
    import pandas as pd
    return pd.isna(val)


@app.route("/api/logs")
def get_logs():
    log_file = "trading_bot.log"
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
    _, _, _, risk_mgr = get_components()
    if not risk_mgr:
        return jsonify({"status": "error", "message": "Risk manager not available"}), 500

    if risk_mgr.is_kill_switch_active:
        risk_mgr.reset_kill_switch()
        state = "reset"
    else:
        risk_mgr._kill_switch_active = True
        state = "activated"

    return jsonify({"status": "success", "message": f"Kill switch {state}"})


def run_dashboard_server(host="0.0.0.0", port=None):
    if port is None:
        port = int(os.environ.get("PORT", 5000))
    logger.info(f"Admin Dashboard running on port {port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)


def start_dashboard_in_background(port=None):
    if port is None:
        port = int(os.environ.get("PORT", 5000))
    t = threading.Thread(target=run_dashboard_server, kwargs={"port": port}, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_dashboard_server()
