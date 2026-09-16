"""Watchlist prices.

Quotes only entries that are both resolved and still trading. An unconfirmed or
delisted ticker is skipped and reported, never guessed at — pricing CCL against
Carnival Corporation when the brief meant Coca-Cola Amatil would produce alerts
about a company nobody is watching.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable

from ..config import WatchlistEntry
from ..runlog import Run
from .http import FetchError
from .yahoo import SOURCE_NAME, Quote, QuoteError, fetch_quote

SOURCE_URL = "https://finance.yahoo.com/quote/{symbol}"


@dataclass(frozen=True)
class WatchlistReading:
    entry: WatchlistEntry
    quote: Quote

    @property
    def pct_change(self) -> float | None:
        return self.quote.pct_change


@dataclass(frozen=True)
class SkippedSymbol:
    symbol: str
    reason: str


def fetch_watchlist(run: Run, entries: Iterable[WatchlistEntry],
                    fetcher=None) -> tuple[list[WatchlistReading],
                                           list[SkippedSymbol],
                                           list[str]]:
    """Fetch quotable entries. Returns readings, deliberate skips, and failures.

    ``fetcher`` is resolved here rather than defaulted in the signature, so that
    patching this module's ``fetch_quote`` actually takes effect. See the note
    in ``macro.fetch_macro``.
    """
    fetcher = fetcher or globals()["fetch_quote"]
    readings: list[WatchlistReading] = []
    skipped: list[SkippedSymbol] = []
    failures: list[str] = []

    for entry in entries:
        if not entry.quotable:
            if not entry.confirmed:
                reason = "ticker not resolved to a listed security"
            elif not entry.active:
                reason = "no longer trading"
            else:
                reason = "no quote symbol configured"
            skipped.append(SkippedSymbol(entry.symbol, reason))
            continue
        try:
            quote = fetcher(entry.quote_symbol)
        except (FetchError, QuoteError) as exc:
            failures.append(f"{entry.symbol} ({entry.quote_symbol}): {exc}")
            run.log_error(f"quote fetch failed for {entry.symbol}", exc)
            continue
        readings.append(WatchlistReading(entry=entry, quote=quote))
        run.log_source(SOURCE_URL.format(symbol=entry.quote_symbol), SOURCE_NAME,
                       "reputable_media")

    run.log("watchlist_fetch",
            {"ok": len(readings), "skipped": len(skipped), "failed": len(failures)})
    return readings, skipped, failures


def store_quotes(conn: sqlite3.Connection, run_id: int,
                 readings: Iterable[WatchlistReading]) -> int:
    """Persist quotes against the *exchange's* trading date, not the Sydney date.

    A NYSE close and an ASX close on the same Sydney morning belong to different
    calendar days, and pretending otherwise would corrupt day-on-day changes.
    """
    stored = 0
    for reading in readings:
        quote = reading.quote
        conn.execute(
            "INSERT INTO watchlist_quotes (run_id, symbol, as_of_date, close, "
            "prev_close, pct_change, currency, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (symbol, as_of_date) DO UPDATE SET "
            "close = excluded.close, prev_close = excluded.prev_close, "
            "pct_change = excluded.pct_change, run_id = excluded.run_id",
            (run_id, reading.entry.symbol, quote.as_of_date, quote.close,
             quote.prev_close, quote.pct_change, quote.currency, SOURCE_NAME),
        )
        stored += 1
    conn.commit()
    return stored


def change_since(conn: sqlite3.Connection, symbol: str, since_date: str) -> float | None:
    """Percentage change from the last close on or before ``since_date``.

    This is the weekly watchlist column. It returns ``None`` rather than a
    misleading zero when there is nothing to compare against.
    """
    latest = conn.execute(
        "SELECT close, as_of_date FROM watchlist_quotes WHERE symbol = ? "
        "ORDER BY as_of_date DESC LIMIT 1", (symbol,)).fetchone()
    if not latest or not latest["close"]:
        return None
    prior = conn.execute(
        "SELECT close FROM watchlist_quotes WHERE symbol = ? AND as_of_date <= ? "
        "AND as_of_date < ? ORDER BY as_of_date DESC LIMIT 1",
        (symbol, since_date, latest["as_of_date"])).fetchone()
    if not prior or not prior["close"]:
        return None
    return (latest["close"] - prior["close"]) / prior["close"] * 100.0
