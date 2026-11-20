"""Live market data feeds. Each returns recent *closed* bars, oldest first.

- ccxt:      crypto from 100+ exchanges, public data, no API key (`pip install ccxt`)
- yahoo:     stocks, ETFs, forex (EURUSD=X), futures (ES=F), indices (`pip install yfinance`)
- synthetic: random prices for demos and dry runs
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from .models import Bar

TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


class Feed:
    def fetch(self, symbol: str, timeframe: str, limit: int) -> list[Bar]:
        raise NotImplementedError


class CCXTFeed(Feed):
    def __init__(self, exchange: str = "binance"):
        import ccxt  # type: ignore

        self.ex = getattr(ccxt, exchange)({"enableRateLimit": True})

    def fetch(self, symbol, timeframe, limit):
        rows = self.ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit + 1)
        bars = [Bar(datetime.fromtimestamp(r[0] / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0)) for r in rows]
        return bars[:-1]  # the last candle is still forming


class YahooFeed(Feed):
    PERIOD_FOR = {"1m": "5d", "5m": "30d", "15m": "30d", "30m": "30d", "1h": "180d", "1d": "2y"}

    def fetch(self, symbol, timeframe, limit):
        import yfinance as yf  # type: ignore

        interval = {"4h": "1h"}.get(timeframe, timeframe)
        df = yf.Ticker(symbol).history(period=self.PERIOD_FOR.get(interval, "2y"), interval=interval,
                                       auto_adjust=True)
        bars = []
        for ts, row in df.iterrows():
            stamp = ts.tz_convert("UTC") if ts.tzinfo else ts
            bars.append(Bar(stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), float(row["Open"]), float(row["High"]),
                            float(row["Low"]), float(row["Close"]), float(row.get("Volume", 0) or 0)))
        if bars and timeframe != "1d":
            bars = bars[:-1]  # drop the in-progress intraday bar
        elif bars:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if bars[-1].timestamp.startswith(today):
                bars = bars[:-1]
        return bars[-limit:]


class SyntheticFeed(Feed):
    """Produces one new random bar per call (after an initial history), for demos without network."""

    def __init__(self, start_price: float = 100.0, vol: float = 0.01, seed: int | None = None):
        self.rng = random.Random(seed)
        self.price = start_price
        self.vol = vol
        self.bars: list[Bar] = []
        self.t = datetime(2025, 1, 1, tzinfo=timezone.utc)

    def _next(self, timeframe: str) -> None:
        o = self.price
        c = o * (1 + self.rng.gauss(0.0002, self.vol))
        hi, lo = max(o, c) * (1 + abs(self.rng.gauss(0, self.vol / 2))), min(o, c) * (1 - abs(self.rng.gauss(0, self.vol / 2)))
        self.bars.append(Bar(self.t.strftime("%Y-%m-%dT%H:%M:%SZ"), o, hi, lo, c, 1000))
        self.t += timedelta(seconds=TIMEFRAME_SECONDS.get(timeframe, 86400))
        self.price = c

    def fetch(self, symbol, timeframe, limit):
        if not self.bars:
            for _ in range(limit):
                self._next(timeframe)
        else:
            self._next(timeframe)
        return self.bars[-limit:]


def build_feed(cfg: dict) -> Feed:
    kind = cfg.get("type", "synthetic")
    if kind == "ccxt":
        return CCXTFeed(cfg.get("exchange", "binance"))
    if kind == "yahoo":
        return YahooFeed()
    if kind == "synthetic":
        return SyntheticFeed(cfg.get("start_price", 100.0), cfg.get("vol", 0.01), cfg.get("seed"))
    raise ValueError(f"unknown feed type: {kind}")
