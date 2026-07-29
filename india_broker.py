"""
india_broker.py — Angel One SmartAPI Broker Module
=====================================================
Wraps Angel One's SmartAPI for Indian stock trading (NSE).

Handles:
  - Auto-login with TOTP generation (no manual OTP needed)
  - Session refresh on token expiry
  - Historical candle data retrieval → pandas DataFrame (cached)
  - Real-time LTP (Last Traded Price) quotes
  - Order placement (NORMAL variety with DELIVERY product)
  - Position tracking and closing

Uses smartapi-python SDK + pyotp for TOTP auto-generation.
"""

import logging
import time
from datetime import datetime, timedelta

import pandas as pd
import pyotp
from SmartApi import SmartConnect

import config
from india_instruments import (
    INDIA_INSTRUMENTS,
    get_token,
    get_trading_symbol,
    get_exchange,
)

logger = logging.getLogger(__name__)


class IndiaBroker:
    """
    Angel One SmartAPI broker client for Indian stock trading.

    Manages authentication, market data, and order execution
    for NSE-listed stocks via the SmartAPI.
    """

    def __init__(self):
        """Initialize the Angel One SmartAPI client."""
        self.api_key = config.ANGEL_API_KEY
        self.client_id = config.ANGEL_CLIENT_ID
        self.pin = config.ANGEL_PIN
        self.totp_secret = config.ANGEL_TOTP_SECRET

        self.smart_api = SmartConnect(api_key=self.api_key)
        self.auth_token = None
        self.feed_token = None
        self._session_time = None
        self._logged_in = False
        self.last_error = ""
        self._last_candle_call_time = 0
        self._candle_cache = {}  # {symbol: (timestamp, dataframe)}

        # Attempt login on initialization
        self.login()

    # -----------------------------------------------------------------------
    # Authentication
    # -----------------------------------------------------------------------
    def login(self) -> bool:
        try:
            if not self.totp_secret or not self.client_id or not self.pin:
                self.last_error = "Missing Angel One credentials in Environment"
                self._logged_in = False
                return False

            clean_secret = self.totp_secret.replace(" ", "").upper()
            totp = pyotp.TOTP(clean_secret).now()

            session_data = self.smart_api.generateSession(
                self.client_id, self.pin, totp
            )

            if session_data and session_data.get("status"):
                self.auth_token = session_data["data"]["jwtToken"]
                self.feed_token = session_data["data"].get("feedToken")
                self._session_time = datetime.now()
                self._logged_in = True
                self.last_error = ""

                logger.info(
                    f"Angel One LOGIN SUCCESS | Client: {self.client_id} | "
                    f"Session active"
                )
                return True
            else:
                msg = session_data.get("message", "Unknown login error") if session_data else "No response from Angel One"
                self.last_error = msg
                logger.error(f"Angel One LOGIN FAILED: {msg}")
                self._logged_in = False
                return False

        except Exception as e:
            err_msg = str(e)
            self.last_error = f"Login Exception: {err_msg}"
            logger.error(f"Angel One LOGIN ERROR: {e}", exc_info=True)
            self._logged_in = False
            return False

    def ensure_session(self):
        if not self._logged_in:
            self.login()
            return

        if self._session_time:
            elapsed = datetime.now() - self._session_time
            if elapsed > timedelta(hours=12):
                logger.info("Angel One session expired — re-authenticating...")
                self.login()

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    # -----------------------------------------------------------------------
    # Account Information
    # -----------------------------------------------------------------------
    def get_account_info(self) -> dict | None:
        self.ensure_session()
        try:
            rms_data = self.smart_api.rmsLimit()
            if rms_data and rms_data.get("status"):
                data = rms_data["data"]
                net = float(data.get("net", 0) or 0)
                available_cash = float(data.get("availablecash", 0) or 0)
                used_margin = float(data.get("utiliseddebits", 0) or 0)

                info = {
                    "equity": net if net > 0 else available_cash,
                    "available_cash": available_cash,
                    "used_margin": used_margin,
                    "net": net,
                }
                logger.info(
                    f"Angel One Account | Net={net:,.2f} | "
                    f"Cash={available_cash:,.2f} | Used={used_margin:,.2f}"
                )
                return info
            else:
                msg = rms_data.get("message", "Unknown") if rms_data else "No response"
                self.last_error = f"Account limit error: {msg}"
                logger.error(f"Failed to fetch Angel One account info: {msg}")
                return None

        except Exception as e:
            self.last_error = f"RMS Error: {e}"
            logger.error(f"Angel One account info error: {e}", exc_info=True)
            return None

    # -----------------------------------------------------------------------
    # Historical Data (with 30s Caching & Rate-Limiting Protection)
    # -----------------------------------------------------------------------
    def get_historical_bars(self, symbol: str, days: int = 300) -> pd.DataFrame | None:
        self.ensure_session()
        token = get_token(symbol)
        exchange = get_exchange(symbol)

        if not token:
            logger.error(f"No instrument token found for {symbol}")
            return None

        # Return cached dataframe if less than 30 seconds old to prevent rate limits
        now_ts = time.time()
        if symbol in self._candle_cache:
            cache_time, cached_df = self._candle_cache[symbol]
            if now_ts - cache_time < 30.0:
                return cached_df

        # Rate-limiting: Ensure 400ms gap between Angel One API calls
        time_since_last = now_ts - self._last_candle_call_time
        if time_since_last < 0.40:
            time.sleep(0.40 - time_since_last)
        self._last_candle_call_time = time.time()

        try:
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days)

            historic_params = {
                "exchange": exchange,
                "symboltoken": token,
                "interval": "ONE_HOUR",
                "fromdate": from_date.strftime("%Y-%m-%d 09:15"),
                "todate": to_date.strftime("%Y-%m-%d 15:30"),
            }

            result = self.smart_api.getCandleData(historic_params)

            if result and result.get("status"):
                candles = result["data"]
                if not candles:
                    logger.warning(f"{symbol}: No candle data returned")
                    return None

                df = pd.DataFrame(
                    candles,
                    columns=["timestamp", "open", "high", "low", "close", "volume"],
                )
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df.set_index("timestamp", inplace=True)
                df = df.astype(float)

                self._candle_cache[symbol] = (time.time(), df)
                logger.debug(f"{symbol}: Fetched {len(df)} candles from Angel One")
                return df
            else:
                msg = result.get("message", "Unknown") if result else "No response"
                logger.warning(f"{symbol}: Failed to fetch candles — {msg}")
                # If cached version exists, return it as fallback
                if symbol in self._candle_cache:
                    return self._candle_cache[symbol][1]
                return None

        except Exception as e:
            logger.error(f"{symbol}: Angel One historical data error: {e}", exc_info=True)
            if symbol in self._candle_cache:
                return self._candle_cache[symbol][1]
            return None

    # -----------------------------------------------------------------------
    # Real-time Quote (LTP)
    # -----------------------------------------------------------------------
    def get_latest_quote(self, symbol: str) -> dict | None:
        self.ensure_session()
        token = get_token(symbol)
        trading_symbol = get_trading_symbol(symbol)
        exchange = get_exchange(symbol)

        if not token or not trading_symbol:
            logger.error(f"No instrument info for {symbol}")
            return None

        try:
            ltp_data = self.smart_api.ltpData(exchange, trading_symbol, token)

            if ltp_data and ltp_data.get("status"):
                data = ltp_data["data"]
                ltp = float(data.get("ltp", 0))

                return {
                    "ltp": ltp,
                    "ask_price": ltp,
                    "symbol": symbol,
                    "exchange": exchange,
                }
            else:
                msg = ltp_data.get("message", "Unknown") if ltp_data else "No response"
                logger.warning(f"{symbol}: LTP fetch failed — {msg}")
                return None

        except Exception as e:
            logger.error(f"{symbol}: LTP error: {e}", exc_info=True)
            return None

    # -----------------------------------------------------------------------
    # Position Tracking
    # -----------------------------------------------------------------------
    def get_open_positions(self) -> dict:
        self.ensure_session()
        try:
            position_data = self.smart_api.position()

            if not position_data or not position_data.get("status"):
                logger.debug("No position data from Angel One")
                return {}

            positions = position_data.get("data", [])
            if not positions:
                return {}

            pos_dict = {}
            for pos in positions:
                net_qty = int(pos.get("netqty", 0))
                if net_qty == 0:
                    continue

                symbol_raw = pos.get("tradingsymbol", "")
                symbol = symbol_raw.replace("-EQ", "")

                buy_price = float(pos.get("averageprice", 0))
                ltp = float(pos.get("ltp", 0))
                pnl = float(pos.get("pnl", 0))
                pnl_pct = ((ltp - buy_price) / buy_price) if buy_price > 0 else 0

                pos_dict[symbol] = {
                    "qty": abs(net_qty),
                    "avg_entry_price": buy_price,
                    "current_price": ltp,
                    "market_value": abs(net_qty) * ltp,
                    "unrealized_pl": pnl,
                    "unrealized_plpc": pnl_pct,
                    "trading_symbol": symbol_raw,
                    "token": pos.get("symboltoken", ""),
                }

            if pos_dict:
                logger.info(f"India positions: {list(pos_dict.keys())}")

            return pos_dict

        except Exception as e:
            logger.error(f"Angel One positions error: {e}", exc_info=True)
            return {}

    # -----------------------------------------------------------------------
    # Order Placement
    # -----------------------------------------------------------------------
    def place_buy_order(
        self,
        symbol: str,
        qty: int,
        limit_price: float,
    ) -> str | None:
        self.ensure_session()
        token = get_token(symbol)
        trading_symbol = get_trading_symbol(symbol)
        exchange = get_exchange(symbol)

        if not token or not trading_symbol:
            logger.error(f"Cannot place order — no instrument info for {symbol}")
            return None

        try:
            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": trading_symbol,
                "symboltoken": token,
                "transactiontype": "BUY",
                "exchange": exchange,
                "ordertype": "LIMIT",
                "producttype": "CNC",
                "duration": "DAY",
                "price": str(round(limit_price, 2)),
                "quantity": str(qty),
            }

            order_id = self.smart_api.placeOrder(order_params)

            logger.info(
                f"BUY ORDER PLACED | {symbol} | "
                f"Qty={qty} | Price={limit_price:.2f} | "
                f"Order ID={order_id}"
            )
            return order_id

        except Exception as e:
            logger.error(f"Failed to place BUY order for {symbol}: {e}", exc_info=True)
            return None

    def place_sell_order(
        self,
        symbol: str,
        qty: int,
        limit_price: float = 0,
        order_type: str = "MARKET",
    ) -> str | None:
        self.ensure_session()
        token = get_token(symbol)
        trading_symbol = get_trading_symbol(symbol)
        exchange = get_exchange(symbol)

        if not token or not trading_symbol:
            logger.error(f"Cannot place sell — no instrument info for {symbol}")
            return None

        try:
            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": trading_symbol,
                "symboltoken": token,
                "transactiontype": "SELL",
                "exchange": exchange,
                "ordertype": order_type,
                "producttype": "CNC",
                "duration": "DAY",
                "quantity": str(qty),
            }

            if order_type == "LIMIT" and limit_price > 0:
                order_params["price"] = str(round(limit_price, 2))

            order_id = self.smart_api.placeOrder(order_params)

            logger.info(
                f"SELL ORDER PLACED | {symbol} | "
                f"Qty={qty} | Type={order_type} | "
                f"Order ID={order_id}"
            )
            return order_id

        except Exception as e:
            logger.error(f"Failed to place SELL order for {symbol}: {e}", exc_info=True)
            return None

    def close_position(self, symbol: str) -> bool:
        positions = self.get_open_positions()
        if symbol not in positions:
            logger.warning(f"{symbol}: No open position to close")
            return False

        qty = positions[symbol]["qty"]
        order_id = self.place_sell_order(symbol, qty, order_type="MARKET")

        if order_id:
            logger.info(f"Position CLOSED for {symbol} (Qty={qty})")
            return True
        return False

    def check_sl_tp(self, risk_mgr) -> list[str]:
        closed_symbols = []
        positions = self.get_open_positions()

        for symbol, pos in positions.items():
            entry_price = pos["avg_entry_price"]
            current_price = pos["current_price"]

            sl_price = risk_mgr.get_stop_loss_price(entry_price)
            tp_price = risk_mgr.get_take_profit_price(entry_price)

            if current_price <= sl_price:
                logger.warning(
                    f"[INDIA SL] {symbol} hit stop-loss! "
                    f"Entry={entry_price:.2f} Current={current_price:.2f} SL={sl_price:.2f}"
                )
                if self.close_position(symbol):
                    closed_symbols.append(symbol)

            elif current_price >= tp_price:
                logger.info(
                    f"[INDIA TP] {symbol} hit take-profit! "
                    f"Entry={entry_price:.2f} Current={current_price:.2f} TP={tp_price:.2f}"
                )
                if self.close_position(symbol):
                    closed_symbols.append(symbol)

        return closed_symbols

    def cancel_all_open_orders(self) -> bool:
        self.ensure_session()
        try:
            order_book = self.smart_api.orderBook()
            if not order_book or not order_book.get("status"):
                return True

            orders = order_book.get("data", [])
            if not orders:
                return True

            cancelled = 0
            for order in orders:
                status = order.get("orderstatus", "").lower()
                if status in ("open", "pending", "trigger pending"):
                    try:
                        self.smart_api.cancelOrder(
                            order["orderid"], order.get("variety", "NORMAL")
                        )
                        cancelled += 1
                    except Exception as e:
                        logger.error(f"Failed to cancel order {order['orderid']}: {e}")

            if cancelled > 0:
                logger.info(f"Cancelled {cancelled} open India orders")
            return True

        except Exception as e:
            logger.error(f"Angel One cancel orders error: {e}", exc_info=True)
            return False

    def logout(self):
        try:
            self.smart_api.terminateSession(self.client_id)
            self._logged_in = False
            logger.info("Angel One session terminated")
        except Exception as e:
            logger.warning(f"Angel One logout error: {e}")
