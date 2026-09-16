"""Yahoo Finance chart API — the numeric price source.

Why not the model: the 8% and 3% alert thresholds must be exact and must fire
every time. Asking a language model for a price would make alerts both expensive
and fallible. This endpoint needs no key, covers ASX and US listings plus
commodity futures and FX, and returns daily closes we can compare arithmetically.

Parsing is kept separate from fetching so tests can run against recorded JSON
without touching the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .http import fetch_json

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range}&interval=1d"
SOURCE_NAME = "Yahoo Finance"


class QuoteError(RuntimeError):
    """The response carried no usable price."""


@dataclass(frozen=True)
class Bar:
    """One daily close, dated in the exchange's own timezone."""

    date: str
    close: float


@dataclass(frozen=True)
class Quote:
    symbol: str
    name: str
    currency: str
    exchange: str
    as_of_date: str
    close: float
    prev_close: float | None
    history: tuple[Bar, ...]
    source: str = SOURCE_NAME

    @property
    def pct_change(self) -> float | None:
        """Day-on-day percentage move, or ``None`` with no prior close."""
        if self.prev_close in (None, 0):
            return None
        return (self.close - self.prev_close) / self.prev_close * 100.0

    def close_on_or_before(self, date: str) -> Bar | None:
        """The most recent bar at or before ``date`` — used for week-on-week."""
        candidates = [bar for bar in self.history if bar.date <= date]
        return candidates[-1] if candidates else None


def parse_chart(payload: Any, symbol: str) -> Quote:
    """Turn a chart API payload into a :class:`Quote`."""
    chart = payload.get("chart") or {}
    if error := chart.get("error"):
        raise QuoteError(f"{symbol}: {error.get('code')} {error.get('description', '')}".strip())

    results = chart.get("result") or []
    if not results:
        raise QuoteError(f"{symbol}: response contained no result")
    result = results[0]

    meta = result.get("meta") or {}
    timestamps = result.get("timestamp") or []
    quote_blocks = (result.get("indicators") or {}).get("quote") or [{}]
    closes = quote_blocks[0].get("close") or []

    tz = ZoneInfo(meta.get("exchangeTimezoneName") or "UTC")
    bars: list[Bar] = []
    for epoch, close in zip(timestamps, closes):
        # A null close is a non-trading day; a zero close is bad data.
        if close is None or epoch is None or close <= 0:
            continue
        bars.append(Bar(datetime.fromtimestamp(epoch, tz).date().isoformat(), float(close)))

    if not bars:
        raise QuoteError(f"{symbol}: response contained no usable closes")

    bars.sort(key=lambda b: b.date)
    return Quote(
        symbol=symbol,
        name=meta.get("longName") or meta.get("shortName") or symbol,
        currency=meta.get("currency") or "",
        exchange=meta.get("fullExchangeName") or meta.get("exchangeName") or "",
        as_of_date=bars[-1].date,
        close=bars[-1].close,
        prev_close=bars[-2].close if len(bars) > 1 else None,
        history=tuple(bars),
    )


def fetch_quote(symbol: str, *, range_: str = "1mo", **kwargs: Any) -> Quote:
    """Fetch and parse one symbol. Raises :class:`~.http.FetchError` or
    :class:`QuoteError`; callers record the failure and carry on with the rest."""
    payload = fetch_json(CHART_URL.format(symbol=symbol, range=range_), **kwargs)
    return parse_chart(payload, symbol)
