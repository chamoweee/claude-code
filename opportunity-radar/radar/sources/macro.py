"""Macro metrics: oil, gold, copper, AUD, and a uranium proxy.

Each metric is fetched as a number, stored with its source and date, and
compared with the previous snapshot to produce the week-on-week column in the
report. Nothing here asks a model for a price.

Two honesty constraints are encoded in the registry rather than left to prose:

* Futures are not spot. Gold and copper come from COMEX front-month contracts
  and say so in ``note``, because a reader comparing them against a spot quote
  elsewhere will see a difference and deserves to know why.
* **There is no free uranium spot price.** ``URA`` is an equity ETF whose price
  is driven by miners, not by the U3O8 term price. It is registered with
  ``is_proxy = True`` and the report must label it a proxy. The actual uranium
  price question is handed to research in Stage 3.

Interest rate decisions (RBA, Fed) and CPI are not market ticks and are not
fetched here — they come from primary sources via research in Stage 3.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable

from ..db import utc_now_iso
from ..runlog import Run
from .http import FetchError
from .yahoo import SOURCE_NAME, Quote, QuoteError, fetch_quote

# Yahoo is an aggregator, not the exchange itself, so its readings are recorded
# as reputable media rather than primary.
SOURCE_STRENGTH = "reputable_media"
SOURCE_URL = "https://finance.yahoo.com/quote/{symbol}"


@dataclass(frozen=True)
class MacroMetric:
    key: str
    symbol: str
    label: str
    unit: str
    note: str = ""
    is_proxy: bool = False


METRICS: tuple[MacroMetric, ...] = (
    MacroMetric("brent", "BZ=F", "Brent crude", "USD/bbl",
                "ICE Brent front-month futures."),
    MacroMetric("gold", "GC=F", "Gold", "USD/oz",
                "COMEX front-month futures, which trade a little away from spot."),
    MacroMetric("copper", "HG=F", "Copper", "USD/lb",
                "COMEX front-month futures. The brief's +38% y/y needs this level to anchor it."),
    MacroMetric("aud_usd", "AUDUSD=X", "AUD/USD", "USD",
                "Also sets the USD to AUD rate used to price API spend."),
    MacroMetric("uranium_ura_proxy", "URA", "Uranium (URA ETF proxy)", "USD",
                "NOT a uranium price. Global X Uranium ETF, driven by miner equities. "
                "There is no free U3O8 spot feed; the real price goes to research.",
                is_proxy=True),
)

METRICS_BY_KEY = {metric.key: metric for metric in METRICS}


@dataclass(frozen=True)
class MacroReading:
    metric: MacroMetric
    quote: Quote

    @property
    def value(self) -> float:
        return self.quote.close

    @property
    def source_url(self) -> str:
        return SOURCE_URL.format(symbol=self.metric.symbol)


@dataclass(frozen=True)
class MetricChange:
    """A metric's move between two stored snapshots."""

    metric: str
    label: str
    unit: str
    latest: float
    previous: float | None
    previous_date: str | None
    is_proxy: bool = False

    @property
    def pct_change(self) -> float | None:
        if self.previous in (None, 0):
            return None
        return (self.latest - self.previous) / self.previous * 100.0

    @property
    def direction(self) -> str:
        pct = self.pct_change
        if pct is None:
            return "new"
        if abs(pct) < 0.05:
            return "flat"
        return "up" if pct > 0 else "down"

    def format_change(self) -> str:
        """The week-on-week cell in the macro table."""
        pct = self.pct_change
        if pct is None:
            return "no prior reading"
        return f"{pct:+.1f}%"


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def fetch_macro(run: Run, metrics: Iterable[MacroMetric] = METRICS,
                fetcher=fetch_quote) -> tuple[list[MacroReading], list[str]]:
    """Fetch every metric. Returns the readings plus one message per failure.

    One bad symbol must not lose the whole macro section, so failures are
    collected and reported rather than raised.
    """
    readings: list[MacroReading] = []
    failures: list[str] = []
    for metric in metrics:
        try:
            quote = fetcher(metric.symbol)
        except (FetchError, QuoteError) as exc:
            failures.append(f"{metric.label} ({metric.symbol}): {exc}")
            run.log_error(f"macro fetch failed for {metric.key}", exc)
            continue
        readings.append(MacroReading(metric=metric, quote=quote))
        run.log_source(SOURCE_URL.format(symbol=metric.symbol), SOURCE_NAME, SOURCE_STRENGTH)
    run.log("macro_fetch", {"ok": len(readings), "failed": len(failures)})
    return readings, failures


def store_macro(conn: sqlite3.Connection, run_id: int, as_of_date: str,
                readings: Iterable[MacroReading]) -> int:
    """Persist readings against the run's Sydney date. Idempotent per day."""
    stored = 0
    for reading in readings:
        metric = reading.metric
        note = metric.note
        if metric.is_proxy:
            note = "PROXY — " + note
        conn.execute(
            "INSERT INTO macro_snapshots (run_id, as_of_date, metric, value, unit, "
            "value_text, source_name, source_url, source_date, source_strength, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            # The unit and note must move with the value. Updating the number
            # but keeping an earlier row's unit produced a fresh copper price
            # labelled "% y/y", which is worse than no reading at all.
            "ON CONFLICT (as_of_date, metric) DO UPDATE SET "
            "value = excluded.value, unit = excluded.unit, "
            "value_text = excluded.value_text, note = excluded.note, "
            "source_name = excluded.source_name, source_url = excluded.source_url, "
            "source_date = excluded.source_date, source_strength = excluded.source_strength, "
            "run_id = excluded.run_id",
            (run_id, as_of_date, metric.key, reading.value, metric.unit,
             f"{reading.value:,.4g} {metric.unit}", SOURCE_NAME, reading.source_url,
             reading.quote.as_of_date, SOURCE_STRENGTH, note),
        )
        stored += 1
    conn.commit()
    return stored


# ---------------------------------------------------------------------------
# Change since the previous snapshot
# ---------------------------------------------------------------------------


def previous_reading(conn: sqlite3.Connection, metric: str,
                     before_date: str) -> sqlite3.Row | None:
    """The most recent stored reading strictly before ``before_date``."""
    return conn.execute(
        "SELECT * FROM macro_snapshots WHERE metric = ? AND as_of_date < ? "
        "AND value IS NOT NULL ORDER BY as_of_date DESC LIMIT 1",
        (metric, before_date),
    ).fetchone()


def changes_since_last_snapshot(conn: sqlite3.Connection, as_of_date: str,
                                readings: Iterable[MacroReading]) -> list[MetricChange]:
    """Build the week-on-week column for the macro table."""
    changes = []
    for reading in readings:
        prior = previous_reading(conn, reading.metric.key, as_of_date)
        changes.append(MetricChange(
            metric=reading.metric.key,
            label=reading.metric.label,
            unit=reading.metric.unit,
            latest=reading.value,
            previous=float(prior["value"]) if prior else None,
            previous_date=prior["as_of_date"] if prior else None,
            is_proxy=reading.metric.is_proxy,
        ))
    return changes


def usd_to_aud_from(readings: Iterable[MacroReading]) -> float | None:
    """Derive the USD->AUD rate from the AUD/USD reading, for the spend ledger.

    AUD/USD is quoted as US dollars per Australian dollar, so the conversion we
    need for pricing an API bill is its reciprocal.
    """
    for reading in readings:
        if reading.metric.key == "aud_usd" and reading.value > 0:
            return 1.0 / reading.value
    return None


def record_fx_rate(conn: sqlite3.Connection, run: Run,
                   readings: Iterable[MacroReading]) -> float | None:
    rate = usd_to_aud_from(readings)
    if rate is not None:
        run.log("fx_rate", {"usd_to_aud": round(rate, 4), "at": utc_now_iso()})
    return rate
