"""
ticker.py - Real-time WebSocket Ticker Module
Zerodha KiteTicker se live price feed receive karo

Features:
- Multiple symbols subscribe kar sakte hain
- Tick data real-time callback ke through milta hai
- Automatic reconnect on disconnect
- Quote, LTP aur Full mode support
"""

import logging
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Callable, Optional

import pytz
from kiteconnect import KiteTicker, KiteConnect

from config import IST

logger = logging.getLogger(__name__)
IST_tz = pytz.timezone("Asia/Kolkata")


class LiveTicker:
    """
    Zerodha KiteTicker wrapper.
    Real-time price updates WebSocket se milte hain.
    
    Usage:
        ticker = LiveTicker(kite, api_key, access_token)
        ticker.subscribe(["RELIANCE", "TCS"], exchange="NSE")
        ticker.start(on_tick=my_callback)
    """

    MODES = {
        "ltp":   KiteTicker.MODE_LTP,     # Sirf LTP
        "quote": KiteTicker.MODE_QUOTE,   # OHLC + LTP + volume
        "full":  KiteTicker.MODE_FULL,    # Poora depth + OI
    }

    def __init__(
        self,
        kite: KiteConnect,
        api_key: str,
        access_token: str,
        mode: str = "quote",
    ):
        self.kite = kite
        self.api_key = api_key
        self.access_token = access_token
        self.tick_mode = self.MODES.get(mode, KiteTicker.MODE_QUOTE)

        # KiteTicker instance
        self.ticker = KiteTicker(api_key, access_token)

        # Subscribed instruments
        self._token_symbol_map: dict[int, str] = {}  # token -> symbol
        self._symbol_token_map: dict[str, int] = {}  # symbol -> token

        # Latest ticks storage
        self._latest_ticks: dict[str, dict] = {}
        self._tick_lock = threading.Lock()

        # Callbacks
        self._on_tick_callbacks: list[Callable] = []
        self._on_connect_callback: Optional[Callable] = None
        self._on_error_callback: Optional[Callable] = None

        # State
        self._running = False
        self._connected = False
        self._reconnect_count = 0

        # Setup ticker callbacks
        self._setup_ticker_callbacks()
        logger.info(f"LiveTicker initialized | Mode: {mode}")

    # ─────────────────────────────────────────────────────────
    # SETUP
    # ─────────────────────────────────────────────────────────

    def _setup_ticker_callbacks(self):
        """KiteTicker ke internal callbacks set karo"""

        def on_connect(ws, response):
            self._connected = True
            self._reconnect_count = 0
            logger.info("✅ WebSocket connected!")

            # Subscriptions restore karo
            tokens = list(self._token_symbol_map.keys())
            if tokens:
                ws.subscribe(tokens)
                ws.set_mode(ws.MODE_QUOTE, tokens)
                logger.info(f"📡 Re-subscribed to {len(tokens)} instruments")

            if self._on_connect_callback:
                self._on_connect_callback()

        def on_ticks(ws, ticks):
            self._process_ticks(ticks)

        def on_close(ws, code, reason):
            self._connected = False
            logger.warning(f"⚠️  WebSocket closed: {code} - {reason}")

        def on_error(ws, code, reason):
            logger.error(f"❌ WebSocket error: {code} - {reason}")
            if self._on_error_callback:
                self._on_error_callback(code, reason)

        def on_reconnect(ws, attempts_count):
            self._reconnect_count = attempts_count
            logger.info(f"🔄 Reconnecting... attempt {attempts_count}")

        def on_noreconnect(ws):
            logger.error("❌ Max reconnects reached. Manual restart needed.")
            self._running = False

        self.ticker.on_ticks = on_ticks
        self.ticker.on_connect = on_connect
        self.ticker.on_close = on_close
        self.ticker.on_error = on_error
        self.ticker.on_reconnect = on_reconnect
        self.ticker.on_noreconnect = on_noreconnect

    # ─────────────────────────────────────────────────────────
    # SUBSCRIBE / UNSUBSCRIBE
    # ─────────────────────────────────────────────────────────

    def subscribe(self, symbols: list[str], exchange: str = "NSE"):
        """
        Symbols ko live feed ke liye subscribe karo.
        
        Args:
            symbols:  ["RELIANCE", "TCS", ...]
            exchange: "NSE" ya "BSE"
        """
        tokens_to_add = []
        for symbol in symbols:
            if symbol in self._symbol_token_map:
                continue  # Already subscribed

            token = self._get_instrument_token(symbol, exchange)
            if token:
                self._token_symbol_map[token] = symbol
                self._symbol_token_map[symbol] = token
                tokens_to_add.append(token)
                logger.debug(f"Queued subscription: {symbol} (token: {token})")

        if tokens_to_add and self._connected:
            self.ticker.subscribe(tokens_to_add)
            self.ticker.set_mode(self.tick_mode, tokens_to_add)
            logger.info(f"📡 Subscribed to {len(tokens_to_add)} new symbols")

        logger.info(f"Total subscribed: {len(self._symbol_token_map)} symbols")

    def unsubscribe(self, symbols: list[str]):
        """Symbols unsubscribe karo"""
        tokens = []
        for symbol in symbols:
            token = self._symbol_token_map.pop(symbol, None)
            if token:
                self._token_symbol_map.pop(token, None)
                tokens.append(token)

        if tokens and self._connected:
            self.ticker.unsubscribe(tokens)
            logger.info(f"Unsubscribed: {symbols}")

    def _ensure_token_cache(self, exchange: str = "NSE") -> dict:
        """Caches instrument tokens in RAM for millisecond resolution."""
        if not hasattr(self, "_token_cache"):
            self._token_cache = {}
        if exchange not in self._token_cache:
            try:
                instruments = self.kite.instruments(exchange)
                lookup = {}
                for inst in instruments:
                    sym = inst.get("tradingsymbol")
                    tok = inst.get("instrument_token")
                    if sym and tok:
                        lookup[sym] = tok
                self._token_cache[exchange] = lookup
                logger.info(f"⚡ Cached {len(lookup)} {exchange} instrument tokens for millisecond WebSocket lookup")
            except Exception as e:
                logger.error(f"Token cache fetch error for {exchange}: {e}")
                self._token_cache[exchange] = {}
        return self._token_cache[exchange]

    def _get_instrument_token(self, symbol: str, exchange: str) -> Optional[int]:
        """Symbol ka instrument token lo (cached in RAM for millisecond resolution)"""
        cache = self._ensure_token_cache(exchange)
        tok = cache.get(symbol)
        if tok:
            return tok
        logger.warning(f"Token not found in cache for {symbol}")
        return None

    # ─────────────────────────────────────────────────────────
    # START / STOP
    # ─────────────────────────────────────────────────────────

    def start(
        self,
        on_tick: Optional[Callable] = None,
        on_connect: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        threaded: bool = True,
    ):
        """
        Ticker start karo.
        
        Args:
            on_tick:    Callback jab naya tick aaye: fn(symbol, tick_data)
            on_connect: Callback jab connect ho
            on_error:   Callback jab error aaye
            threaded:   Background thread mein run karo (default True)
        """
        if on_tick:
            self._on_tick_callbacks.append(on_tick)
        if on_connect:
            self._on_connect_callback = on_connect
        if on_error:
            self._on_error_callback = on_error

        self._running = True
        logger.info("🚀 Starting LiveTicker...")

        # Reconnect settings
        if hasattr(self.ticker, "enable_reconnect"):
            try:
                self.ticker.enable_reconnect(reconnect_max_tries=10, reconnect_max_delay=60)
            except Exception:
                pass
        else:
            try:
                self.ticker.RECONNECT_MAX_TRIES = 10
                self.ticker.RECONNECT_MAX_DELAY = 60
            except Exception:
                pass

        # Connect karo
        self.ticker.connect(threaded=threaded)

    def stop(self):
        """Ticker band karo"""
        self._running = False
        try:
            self.ticker.stop()
            self._connected = False
            logger.info("🛑 LiveTicker stopped")
        except Exception as e:
            logger.error(f"Ticker stop error: {e}")

    # ─────────────────────────────────────────────────────────
    # TICK PROCESSING
    # ─────────────────────────────────────────────────────────

    def _process_ticks(self, ticks: list):
        """Incoming ticks process karo"""
        for tick in ticks:
            token = tick.get("instrument_token")
            symbol = self._token_symbol_map.get(token)
            if not symbol:
                continue

            # Parsed tick data
            parsed = self._parse_tick(symbol, tick)

            # Latest tick update karo (thread-safe)
            with self._tick_lock:
                self._latest_ticks[symbol] = parsed

            # Callbacks call karo
            for callback in self._on_tick_callbacks:
                try:
                    callback(symbol, parsed)
                except Exception as e:
                    logger.error(f"Tick callback error: {e}")

    @staticmethod
    def _parse_tick(symbol: str, tick: dict) -> dict:
        """Raw tick data ko clean format mein parse karo"""
        ohlc = tick.get("ohlc", {})
        depth = tick.get("depth", {})

        return {
            "symbol":       symbol,
            "ltp":          tick.get("last_price", 0),
            "open":         ohlc.get("open", 0),
            "high":         ohlc.get("high", 0),
            "low":          ohlc.get("low", 0),
            "close":        ohlc.get("close", 0),
            "volume":       tick.get("volume_traded", 0),
            "buy_qty":      tick.get("total_buy_quantity", 0),
            "sell_qty":     tick.get("total_sell_quantity", 0),
            "change":       tick.get("change", 0),
            "change_pct":   tick.get("last_price", 0) / ohlc.get("close", 1) * 100 - 100 if ohlc.get("close", 0) > 0 else 0,
            "avg_price":    tick.get("average_traded_price", 0),
            "timestamp":    tick.get("exchange_timestamp", datetime.now(IST_tz)),
            # Market depth (full mode mein)
            "best_bid":     depth.get("buy", [{}])[0].get("price", 0) if depth.get("buy") else 0,
            "best_ask":     depth.get("sell", [{}])[0].get("price", 0) if depth.get("sell") else 0,
        }

    # ─────────────────────────────────────────────────────────
    # DATA ACCESS
    # ─────────────────────────────────────────────────────────

    def get_ltp(self, symbol: str) -> Optional[float]:
        """Symbol ka latest LTP"""
        with self._tick_lock:
            tick = self._latest_ticks.get(symbol)
            return tick["ltp"] if tick else None

    def get_tick(self, symbol: str) -> Optional[dict]:
        """Symbol ka latest full tick"""
        with self._tick_lock:
            return self._latest_ticks.get(symbol)

    def get_all_ticks(self) -> dict:
        """Saare subscribed symbols ke latest ticks"""
        with self._tick_lock:
            return self._latest_ticks.copy()

    def get_ltp_map(self) -> dict[str, float]:
        """Saare symbols ke LTP ek dict mein"""
        with self._tick_lock:
            return {s: t["ltp"] for s, t in self._latest_ticks.items()}

    def add_tick_callback(self, callback: Callable):
        """Naya tick callback add karo"""
        self._on_tick_callbacks.append(callback)

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def subscribed_symbols(self) -> list[str]:
        return list(self._symbol_token_map.keys())

    def get_status(self) -> dict:
        return {
            "connected":     self._connected,
            "subscribed":    len(self._symbol_token_map),
            "ticks_received": len(self._latest_ticks),
            "reconnects":    self._reconnect_count,
            "mode":          self.tick_mode,
        }
