"""
backtest.py — Simple historical backtest for strategy comparison
================================================================
Runs trend_pullback vs mean_reversion on daily or hourly bars.

Examples:
  python backtest.py --market US --strategy trend_pullback --timeframe 1Day
  python backtest.py --market US --compare
  python backtest.py --csv path/to/bars.csv --strategy mean_reversion

CSV columns required: timestamp,open,high,low,close[,volume]
Without live API keys, use --csv or the synthetic demo mode.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

import config
from strategy import create_strategy, calc_atr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger("backtest")


@dataclass
class BacktestResult:
    strategy: str
    symbol: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    net_pnl: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    equity_curve: list[float] = field(default_factory=list)


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for need in ("open", "high", "low", "close", "volume"):
        if need in cols:
            rename[cols[need]] = need
    if "timestamp" in cols:
        rename[cols["timestamp"]] = "timestamp"
    elif "date" in cols:
        rename[cols["date"]] = "timestamp"
    df = df.rename(columns=rename)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df.sort_index()


def synthetic_bars(n: int = 400, seed: int = 42) -> pd.DataFrame:
    """Deterministic demo series for offline smoke tests."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0004, 0.012, n)
    close = 100 * np.cumprod(1 + rets)
    high = close * (1 + rng.uniform(0.001, 0.01, n))
    low = close * (1 - rng.uniform(0.001, 0.01, n))
    open_ = close * (1 + rng.normal(0, 0.002, n))
    volume = rng.integers(100_000, 2_000_000, n).astype(float)
    idx = pd.date_range("2023-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def fetch_alpaca_bars(symbol: str, timeframe: str, lookback: int) -> Optional[pd.DataFrame]:
    if config.IS_PLACEHOLDER_KEY:
        return None
    try:
        from data_feed import DataFeed, TIMEFRAME_MAP
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.historical import StockHistoricalDataClient
        from datetime import datetime, timedelta

        # Temporarily override timeframe via request
        old_tf = config.TIMEFRAME
        old_lb = config.LOOKBACK_BARS
        config.TIMEFRAME = timeframe
        config.LOOKBACK_BARS = lookback
        try:
            feed = DataFeed()
            df = feed.get_historical_bars(symbol)
        finally:
            config.TIMEFRAME = old_tf
            config.LOOKBACK_BARS = old_lb
        return df
    except Exception as e:
        logger.error(f"Alpaca fetch failed: {e}")
        return None


def run_backtest(
    df: pd.DataFrame,
    strategy_name: str,
    market: str = "US",
    symbol: str = "SYM",
    initial_equity: float = 100_000.0,
    risk_per_trade: float | None = None,
    atr_stop_mult: float | None = None,
    take_profit_r: float | None = None,
) -> BacktestResult:
    risk_pct = risk_per_trade if risk_per_trade is not None else config.RISK_PER_TRADE
    atr_mult = atr_stop_mult if atr_stop_mult is not None else config.ATR_STOP_MULT
    tp_r = take_profit_r if take_profit_r is not None else config.TAKE_PROFIT_R

    strategy = create_strategy(market=market, name=strategy_name)
    data = strategy.compute_indicators(df)

    equity = initial_equity
    peak = equity
    max_dd = 0.0
    curve = [equity]

    position = None  # {qty, entry, stop, tp, atr}
    wins = losses = 0
    gross_profit = gross_loss = 0.0
    trade_count = 0

    # Need enough bars for indicators
    start_i = max(config.SMA_SLOW, 50) + 2

    for i in range(start_i, len(data)):
        window = data.iloc[: i + 1]
        bar = data.iloc[i]
        price = float(bar["close"])
        atr = float(bar["ATR"]) if not pd.isna(bar.get("ATR")) else None

        # Manage open position on this bar
        if position is not None:
            # Update trailing after 1R
            risk = position["entry"] - position["initial_stop"]
            peak_px = max(position.get("peak", position["entry"]), price)
            position["peak"] = peak_px
            if risk > 0 and (peak_px - position["entry"]) >= risk and atr and atr > 0:
                trail = peak_px - (config.ATR_TRAIL_MULT * atr)
                position["stop"] = max(position["stop"], trail)

            exit_px = None
            reason = None
            # Intrabar approx: check high/low vs SL/TP
            low = float(bar["low"])
            high = float(bar["high"])
            if low <= position["stop"]:
                exit_px = position["stop"]
                reason = "sl"
            elif high >= position["tp"]:
                exit_px = position["tp"]
                reason = "tp"
            else:
                # Strategy sell signal
                sig = strategy.generate_signal(window, symbol)
                if sig == "SELL":
                    exit_px = price
                    reason = "signal"

            if exit_px is not None:
                pnl = (exit_px - position["entry"]) * position["qty"]
                equity += pnl
                trade_count += 1
                if pnl >= 0:
                    wins += 1
                    gross_profit += pnl
                else:
                    losses += 1
                    gross_loss += abs(pnl)
                position = None

        else:
            sig = strategy.generate_signal(window, symbol)
            if sig == "BUY" and atr and atr > 0:
                stop = price - atr_mult * atr
                stop_dist = price - stop
                if stop_dist <= 0:
                    continue
                risk_budget = equity * risk_pct
                qty = int(risk_budget // stop_dist)
                max_by_pct = int((equity * config.MAX_POSITION_PCT) // price)
                qty = min(qty, max_by_pct, config.MAX_SHARES_PER_ORDER)
                if qty <= 0:
                    continue
                tp = price + tp_r * stop_dist
                position = {
                    "qty": qty,
                    "entry": price,
                    "stop": stop,
                    "initial_stop": stop,
                    "tp": tp,
                    "atr": atr,
                    "peak": price,
                }

        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
        curve.append(equity)

    # Force close at end
    if position is not None:
        price = float(data.iloc[-1]["close"])
        pnl = (price - position["entry"]) * position["qty"]
        equity += pnl
        trade_count += 1
        if pnl >= 0:
            wins += 1
            gross_profit += pnl
        else:
            losses += 1
            gross_loss += abs(pnl)
        curve.append(equity)

    pf = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    return BacktestResult(
        strategy=strategy_name,
        symbol=symbol,
        trades=trade_count,
        wins=wins,
        losses=losses,
        net_pnl=round(equity - initial_equity, 2),
        win_rate=round(wins / trade_count, 4) if trade_count else 0.0,
        profit_factor=round(pf, 4),
        max_drawdown=round(max_dd, 4),
        equity_curve=curve,
    )


def print_result(r: BacktestResult):
    print(
        f"\n=== {r.strategy} @ {r.symbol} ===\n"
        f"  Trades:        {r.trades}\n"
        f"  Win rate:      {r.win_rate:.1%}\n"
        f"  Profit factor: {r.profit_factor:.2f}\n"
        f"  Net PnL:       {r.net_pnl:+,.2f}\n"
        f"  Max drawdown:  {r.max_drawdown:.1%}\n"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backtest pluggable strategies")
    parser.add_argument("--market", default="US", choices=["US", "INDIA"])
    parser.add_argument(
        "--strategy",
        default=config.STRATEGY_NAME,
        help="trend_pullback | mean_reversion",
    )
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--timeframe", default="1Day", help="1Day or 1Hour")
    parser.add_argument("--lookback", type=int, default=500)
    parser.add_argument("--csv", default=None, help="OHLCV CSV path")
    parser.add_argument("--compare", action="store_true", help="Run both strategies")
    parser.add_argument("--demo", action="store_true", help="Use synthetic bars")
    parser.add_argument("--equity", type=float, default=100_000.0)
    args = parser.parse_args(argv)

    if args.csv:
        df = load_csv(args.csv)
        symbol = args.symbol
    elif args.demo or config.IS_PLACEHOLDER_KEY:
        logger.info("Using synthetic demo bars (no API / --demo)")
        df = synthetic_bars()
        symbol = "DEMO"
    else:
        df = fetch_alpaca_bars(args.symbol, args.timeframe, args.lookback)
        symbol = args.symbol
        if df is None or df.empty:
            logger.warning("No live bars — falling back to synthetic demo")
            df = synthetic_bars()
            symbol = "DEMO"

    strategies = (
        ["trend_pullback", "mean_reversion"] if args.compare else [args.strategy]
    )
    results = []
    for name in strategies:
        r = run_backtest(
            df,
            strategy_name=name,
            market=args.market,
            symbol=symbol,
            initial_equity=args.equity,
        )
        print_result(r)
        results.append(r)

    if args.compare and len(results) == 2:
        a, b = results
        better = a if a.net_pnl >= b.net_pnl else b
        print(
            f"Higher net PnL: {better.strategy} "
            f"({better.net_pnl:+,.2f} vs "
            f"{(b if better is a else a).net_pnl:+,.2f})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
