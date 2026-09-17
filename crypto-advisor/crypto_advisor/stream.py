"""Binance public WebSocket ticker stream (no account/keys needed) for
near-real-time prices, with automatic reconnect and a REST-polling fallback
when the socket is unavailable (e.g. geo-blocked network, or a genuine
outage). Prices from this module are USD; the report layer converts to AUD
using the CoinGecko AUD/USD cross from `/global` or a direct AUD quote.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field

from .logutil import get_logger

logger = get_logger(__name__)

try:
    import websocket  # websocket-client
except ImportError:  # pragma: no cover - exercised only if dependency missing
    websocket = None


@dataclass
class StreamState:
    prices: dict[str, float] = field(default_factory=dict)
    last_update: dict[str, float] = field(default_factory=dict)
    connected: bool = False
    last_connect_attempt: float = 0.0
    consecutive_failures: int = 0


class PriceStream:
    """Subscribes to Binance's combined miniTicker stream for a fixed symbol
    list (e.g. ["btcusdt", "ethusdt", ...]) and keeps a live in-memory price
    map. Safe to run in a background thread; `get_price` never blocks.
    """

    def __init__(self, symbols: list[str], base_ws_url: str = "wss://stream.binance.com:9443",
                 stale_after_seconds: int = 60, max_backoff_seconds: int = 60):
        self.symbols = [s.lower() for s in symbols]
        self.base_ws_url = base_ws_url
        self.stale_after_seconds = stale_after_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.state = StreamState()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws: "websocket.WebSocketApp | None" = None

    def _stream_url(self) -> str:
        streams = "/".join(f"{s}@miniTicker" for s in self.symbols)
        return f"{self.base_ws_url}/stream?streams={streams}"

    def _on_message(self, _ws, message: str) -> None:
        try:
            payload = json.loads(message)
            data = payload.get("data", payload)
            symbol = data.get("s", "").lower()
            close_price = data.get("c")
            if symbol and close_price is not None:
                self.state.prices[symbol] = float(close_price)
                self.state.last_update[symbol] = time.time()
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("failed to parse WS message: %s", exc)

    def _on_open(self, _ws) -> None:
        logger.info("Binance WS connected (%d symbols)", len(self.symbols))
        self.state.connected = True
        self.state.consecutive_failures = 0

    def _on_close(self, _ws, *_args) -> None:
        logger.warning("Binance WS closed")
        self.state.connected = False

    def _on_error(self, _ws, error) -> None:
        logger.warning("Binance WS error: %s", error)
        self.state.connected = False

    def _run_forever_with_reconnect(self) -> None:
        if websocket is None:
            logger.warning("websocket-client not installed; live stream disabled, using REST fallback only")
            return
        while not self._stop.is_set():
            self.state.last_connect_attempt = time.time()
            try:
                self._ws = websocket.WebSocketApp(
                    self._stream_url(),
                    on_message=self._on_message,
                    on_open=self._on_open,
                    on_close=self._on_close,
                    on_error=self._on_error,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Binance WS run_forever raised: %s", exc)
            self.state.connected = False
            if self._stop.is_set():
                break
            self.state.consecutive_failures += 1
            backoff = min(self.max_backoff_seconds, 2 ** min(self.state.consecutive_failures, 6))
            logger.info("Reconnecting to Binance WS in %ds (failure #%d)", backoff, self.state.consecutive_failures)
            self._stop.wait(backoff)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_forever_with_reconnect, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self._thread:
            self._thread.join(timeout=5)

    def is_stale(self, symbol: str) -> bool:
        last = self.state.last_update.get(symbol.lower())
        if last is None:
            return True
        return (time.time() - last) > self.stale_after_seconds

    def get_price(self, symbol: str) -> float | None:
        """Returns the live WS price, or None if we have no fresh data (caller
        should fall back to REST -- see `get_price_with_rest_fallback`)."""
        symbol = symbol.lower()
        if self.is_stale(symbol):
            return None
        return self.state.prices.get(symbol)

    def get_price_with_rest_fallback(self, symbol: str, rest_fallback_fn) -> tuple[float | None, bool]:
        """Returns (price, is_stale). Tries the live stream first; if stale or
        missing, calls `rest_fallback_fn()` (e.g. a CoinGecko lookup) and
        marks the result as stale so the report can show a warning."""
        price = self.get_price(symbol)
        if price is not None:
            return price, False
        try:
            fallback_price = rest_fallback_fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning("REST fallback failed for %s: %s", symbol, exc)
            fallback_price = None
        return fallback_price, True
