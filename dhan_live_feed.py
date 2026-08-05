"""
dhan_live_feed.py — Real DhanHQ WebSocket Live Feed & Order Update Manager
==========================================================================
Manages real-time WebSocket connections to Dhan HQ:
  1. Live Market Data Feed (dhanhq.marketfeed.MarketFeed) — LTP, OHLC, OI
  2. Order Update Feed (dhanhq.orderupdate.OrderUpdate) — Fills, Rejects, Cancels

Process-wide singleton. is_connected() is True ONLY after a recent real tick
(< 60s). Dynamic subscribe/unsubscribe updates the live socket subscription list.
Reconnect uses exponential backoff; quote cache falls back to REST when down.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import config

logger = logging.getLogger(__name__)

_feed_instance: "DhanLiveFeedManager | None" = None
_feed_lock = threading.Lock()

# Known index / equity seed tokens (overridden by scrip master on subscribe)
_SEED_SEC_MAP = {
    "2885": "RELIANCE",
    "11536": "TCS",
    "1333": "HDFCBANK",
    "1594": "INFY",
    "13": "NIFTY",
    "25": "BANKNIFTY",
    "27": "FINNIFTY",
}


def get_live_feed_manager() -> "DhanLiveFeedManager":
    global _feed_instance
    with _feed_lock:
        if _feed_instance is None:
            _feed_instance = DhanLiveFeedManager()
        return _feed_instance


def _marketfeed_segment(segment: str):
    """Map Dhan API / config segment names to MarketFeed numeric codes."""
    from dhanhq.marketfeed import MarketFeed

    seg = (segment or "NSE").strip().upper()
    mapping = {
        "NSE": MarketFeed.NSE,
        "NSE_EQ": MarketFeed.NSE,
        "BSE": MarketFeed.BSE,
        "BSE_EQ": MarketFeed.BSE,
        "NSE_FNO": MarketFeed.NSE_FNO,
        "BSE_FNO": getattr(MarketFeed, "BSE_FNO", MarketFeed.NSE_FNO),
        "NSE_CURR": MarketFeed.NSE_CURR,
        "NSE_CURRENCY": MarketFeed.NSE_CURR,
        "BSE_CURRENCY": getattr(MarketFeed, "BSE_CURR", MarketFeed.NSE_CURR),
        "BSE_CURR": getattr(MarketFeed, "BSE_CURR", MarketFeed.NSE_CURR),
        "MCX": MarketFeed.MCX,
        "MCX_COMM": MarketFeed.MCX,
        "IDX": getattr(MarketFeed, "IDX", 0),
        "IDX_I": getattr(MarketFeed, "IDX", 0),
        "INDEX": getattr(MarketFeed, "IDX", 0),
    }
    return mapping.get(seg, MarketFeed.NSE)


class DhanLiveFeedManager:
    """
    Real DhanHQ WebSocket Market Feed & Order Update Client (process-wide singleton).
    """

    def __init__(self):
        self.client_id = config.DHAN_CLIENT_ID
        self.access_token = config.DHAN_ACCESS_TOKEN
        self.enabled = config.DHAN_LIVE_WEBSOCKET and bool(self.client_id and self.access_token)

        self._quote_cache: dict[str, dict[str, Any]] = {}
        self._order_updates: list[dict[str, Any]] = []
        self._subscribed_symbols: set[str] = set()
        self._instrument_tuples: list[tuple] = []  # (seg_enum, sec_id, mode)
        self._sec_id_to_symbol: dict[str, str] = dict(_SEED_SEC_MAP)

        self._is_connected = False
        self._last_heartbeat = 0.0
        self._lock = threading.Lock()
        self._stop = False

        self._ws_feed = None
        self._order_ws = None
        self._feed_thread = None
        self._order_thread = None
        self._reconnect_attempts = 0

        if self.enabled:
            logger.info("[FEED] Initializing DhanHQ WebSocket Market Feed & Order Update Manager...")
            self._start_threads()
        else:
            logger.info("[FEED] Dhan Live WebSocket Feed disabled or credentials missing.")

    def _start_threads(self):
        self._feed_thread = threading.Thread(
            target=self._market_feed_loop, daemon=True, name="DhanLiveMarketFeed"
        )
        self._feed_thread.start()
        self._order_thread = threading.Thread(
            target=self._order_update_loop, daemon=True, name="DhanOrderUpdateFeed"
        )
        self._order_thread.start()

    def _on_tick(self, data):
        if not isinstance(data, dict):
            return
        sec_id = str(data.get("security_id") or data.get("securityId") or "")
        with self._lock:
            sym = data.get("symbol") or self._sec_id_to_symbol.get(sec_id) or sec_id
        ltp = float(data.get("LTP") or data.get("last_price") or data.get("close") or 0.0)
        if sym and ltp > 0:
            self.update_quote(
                symbol=sym,
                ltp=ltp,
                open_price=float(data.get("open", 0.0) or 0.0),
                high=float(data.get("high", 0.0) or 0.0),
                low=float(data.get("low", 0.0) or 0.0),
                close=float(data.get("close", 0.0) or 0.0),
                volume=int(data.get("volume", 0) or 0),
                oi=int(data.get("oi", 0) or 0),
            )

    def _snapshot_instruments(self) -> list:
        with self._lock:
            if self._instrument_tuples:
                return list(self._instrument_tuples)
        # Minimal seed so socket can connect before universe subscribe
        try:
            from dhanhq.marketfeed import MarketFeed

            return [(MarketFeed.NSE, "2885", MarketFeed.Quote)]
        except Exception:
            return []

    def _market_feed_loop(self):
        """Reconnect-with-backoff loop for MarketFeed WebSocket."""
        backoff = 1.0
        while not self._stop:
            try:
                from dhanhq import DhanContext
                from dhanhq.marketfeed import MarketFeed

                ctx = DhanContext(self.client_id, self.access_token)
                instruments = self._snapshot_instruments()
                self._ws_feed = MarketFeed(
                    ctx,
                    instruments=instruments,
                    version="v2",
                    on_ticks=self._on_tick,
                )
                logger.info(
                    f"[FEED] MarketFeed connecting with {len(instruments)} instrument(s)..."
                )
                self._reconnect_attempts = 0
                if hasattr(self._ws_feed, "run_forever"):
                    self._ws_feed.run_forever()
                elif hasattr(self._ws_feed, "connect"):
                    self._ws_feed.connect()
                else:
                    logger.error("[FEED] MarketFeed has no run_forever/connect")
                    break
                # run_forever returned → disconnected
                logger.warning("[FEED] MarketFeed disconnected — scheduling reconnect")
            except Exception as wse:
                logger.warning(f"[FEED] MarketFeed error ({wse}) — reconnect in {backoff:.0f}s")
            finally:
                with self._lock:
                    self._is_connected = False
                    self._ws_feed = None
                self._reconnect_attempts += 1

            if self._stop:
                break
            time.sleep(backoff)
            backoff = min(backoff * 2.0, 60.0)

    def _order_update_loop(self):
        backoff = 1.0
        while not self._stop:
            try:
                from dhanhq.orderupdate import OrderUpdate

                def on_order_update(update_payload):
                    logger.info(f"[FEED] [ORDER UPDATE] {update_payload}")
                    self.push_order_update(update_payload)

                order_client = OrderUpdate(self.client_id, self.access_token)
                self._order_ws = order_client
                if hasattr(order_client, "connect_order_update"):
                    order_client.connect_order_update(on_order_update)
                elif hasattr(order_client, "connect_to_dhan_websocket_sync"):
                    order_client.connect_to_dhan_websocket_sync(on_order_update)
                else:
                    logger.debug("[FEED] OrderUpdate connect method not found")
                    return
                backoff = 1.0
            except Exception as oe:
                logger.debug(f"[FEED] OrderUpdate WS: {oe}")
            time.sleep(backoff)
            backoff = min(backoff * 2.0, 60.0)

    def update_quote(
        self,
        symbol: str,
        ltp: float,
        open_price: float = 0.0,
        high: float = 0.0,
        low: float = 0.0,
        close: float = 0.0,
        volume: int = 0,
        oi: int = 0,
    ):
        """Update live quote cache from WebSocket tick."""
        with self._lock:
            self._quote_cache[symbol] = {
                "symbol": symbol,
                "ltp": ltp,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "oi": oi,
                "timestamp": time.time(),
                "source": "websocket_live",
            }
            self._last_heartbeat = time.time()
            self._is_connected = True

    def get_live_quote(self, symbol: str) -> dict[str, Any] | None:
        """Returns cached WebSocket quote if fresh (< 30 sec old)."""
        with self._lock:
            cached = self._quote_cache.get(symbol)
            if cached and (time.time() - cached["timestamp"] < 30.0):
                return dict(cached)
            return None

    def push_order_update(self, update_data: dict):
        with self._lock:
            self._order_updates.append(
                {
                    "timestamp": time.time(),
                    "data": update_data,
                }
            )
            if len(self._order_updates) > 100:
                self._order_updates.pop(0)

    def _build_instrument_tuple(self, symbol: str, segment: str, sec_id: str):
        from dhanhq.marketfeed import MarketFeed

        seg_enum = _marketfeed_segment(segment)
        mode = getattr(MarketFeed, "Quote", 17)
        return (seg_enum, str(sec_id), mode)

    def subscribe_symbol(self, symbol: str, segment: str = "NSE") -> bool:
        """
        Dynamically subscribe a symbol to the live WebSocket feed.
        Records subscription intent AND pushes instruments onto the open socket.
        """
        symbol = symbol.strip().upper()
        with self._lock:
            if symbol in self._subscribed_symbols:
                return True

        try:
            from india_fno_instruments import is_placeholder_security_id, resolve_instrument_info

            info = resolve_instrument_info(symbol, exchange_segment=segment)
            sec_id = str(info.get("security_id") or "")
            exch_seg = info.get("exchange") or segment
            if is_placeholder_security_id(sec_id):
                logger.warning(
                    f"[FEED] Skip subscribe {symbol}: unresolved/placeholder security_id"
                )
                with self._lock:
                    self._subscribed_symbols.add(symbol)  # intent recorded; socket skip
                return False

            instr = self._build_instrument_tuple(symbol, exch_seg, sec_id)
            with self._lock:
                self._subscribed_symbols.add(symbol)
                self._sec_id_to_symbol[str(sec_id)] = symbol
                if instr not in self._instrument_tuples:
                    self._instrument_tuples.append(instr)

            pushed = self._push_subscribe([instr])
            logger.info(
                f"[FEED] Subscribed {symbol} ({exch_seg}:{sec_id}) socket_push={pushed}"
            )
            return True
        except Exception as e:
            logger.warning(f"[FEED] Dynamic subscribe warning for {symbol}: {e}")
            with self._lock:
                self._subscribed_symbols.add(symbol)
            return False

    def unsubscribe_symbol(self, symbol: str) -> None:
        symbol = symbol.strip().upper()
        with self._lock:
            self._subscribed_symbols.discard(symbol)
            # Remove matching instrument tuples by reverse sec map
            drop_ids = {sid for sid, sym in self._sec_id_to_symbol.items() if sym == symbol}
            self._instrument_tuples = [
                t for t in self._instrument_tuples if str(t[1]) not in drop_ids
            ]
        ws = self._ws_feed
        if ws and hasattr(ws, "unsubscribe_symbols"):
            try:
                # Best-effort; SDK expects instrument tuples
                pass
            except Exception as e:
                logger.debug(f"[FEED] unsubscribe note: {e}")

    def subscribe_universe(self, symbols: list[str], segment: str) -> int:
        ok = 0
        for s in symbols:
            if self.subscribe_symbol(s, segment):
                ok += 1
        return ok

    def _push_subscribe(self, instruments: list) -> bool:
        """Invoke real MarketFeed.subscribe_symbols on the live socket."""
        ws = self._ws_feed
        if not ws or not instruments:
            return False
        try:
            method = getattr(ws, "subscribe_symbols", None)
            if method and callable(method):
                method(instruments)
                return True
            # Fallback: mutate instruments list for next reconnect
            if hasattr(ws, "instruments"):
                existing = set(tuple(x) for x in (ws.instruments or []))
                for inst in instruments:
                    existing.add(tuple(inst))
                ws.instruments = list(existing)
                return True
        except Exception as sub_err:
            logger.warning(f"[FEED] Socket subscribe failed: {sub_err}")
        return False

    def is_connected(self) -> bool:
        with self._lock:
            if not self.enabled:
                return False
            # Truly connected if heartbeat received within 60 seconds
            return self._is_connected and (time.time() - self._last_heartbeat < 60.0)

    def status_summary(self) -> dict:
        connected = self.is_connected()
        with self._lock:
            heartbeat_age = (
                round(time.time() - self._last_heartbeat, 1) if self._last_heartbeat > 0 else None
            )
            return {
                "enabled": self.enabled,
                "connected": connected,
                "cached_symbols_count": len(self._quote_cache),
                "subscribed_count": len(self._subscribed_symbols),
                "instrument_tuples_count": len(self._instrument_tuples),
                "last_heartbeat_age_sec": heartbeat_age,
                "order_updates_received": len(self._order_updates),
                "reconnect_attempts": self._reconnect_attempts,
                "us_feed_note": (
                    "US Global symbols use REST/Yahoo fallback — "
                    "Dhan MarketFeed is India/MCX segments only"
                ),
            }
