"""The alert rule engine.

Deliberately free of any model call. These rules decide whether Chamk's phone
buzzes at 7am, so they must be exact, cheap and repeatable: given the same
quotes they fire identically every time, and they cannot invent a move that did
not happen or miss one that did.

Stage 2 implements the three price-driven rules. The remaining triggers from the
brief — RBA/Fed decisions, major CPI, battery rebate rule changes, and major
news on a tracked theme — are not market ticks and arrive from research in
Stage 3. They reuse the :class:`Alert` shape and the dedupe path below, so the
daily job's "email only if something fired" logic is written once, here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Iterable

from ..config import AlertThresholds
from ..db import utc_now_iso
from ..sources.macro import MacroReading
from ..sources.quotes import WatchlistReading

# Which macro metrics are judged against the commodity threshold vs the FX one.
COMMODITY_METRICS = frozenset({"brent", "gold", "copper"})
FX_METRICS = frozenset({"aud_usd"})


@dataclass(frozen=True)
class Alert:
    rule: str
    subject: str
    headline: str
    detail: str = ""
    severity: str = "notable"
    source_url: str = ""
    sydney_date: str = ""
    dedupe_key: str = field(default="")

    def with_context(self, sydney_date: str) -> "Alert":
        """Attach the run's date and derive the dedupe key from it."""
        return Alert(
            rule=self.rule, subject=self.subject, headline=self.headline,
            detail=self.detail, severity=self.severity, source_url=self.source_url,
            sydney_date=sydney_date,
            dedupe_key=self.dedupe_key or f"{self.rule}:{self.subject}:{sydney_date}",
        )


def _severity(magnitude: float, threshold: float) -> str:
    """Twice the threshold is worth a stronger word than just over it."""
    return "urgent" if magnitude >= threshold * 2 else "notable"


def _direction(pct: float) -> str:
    return "rose" if pct > 0 else "fell"


# ---------------------------------------------------------------------------
# Price-driven rules
# ---------------------------------------------------------------------------


def watchlist_alerts(readings: Iterable[WatchlistReading],
                     thresholds: AlertThresholds) -> list[Alert]:
    """A watchlist stock moving more than the daily threshold."""
    alerts = []
    for reading in readings:
        pct = reading.pct_change
        if pct is None or abs(pct) <= thresholds.watchlist_move_pct:
            continue
        quote = reading.quote
        alerts.append(Alert(
            rule="watchlist_move",
            subject=reading.entry.symbol,
            headline=f"{reading.entry.symbol} {_direction(pct)} {abs(pct):.1f}% "
                     f"to {quote.close:,.2f} {quote.currency}",
            detail=f"{reading.entry.name} on {quote.exchange}, close for "
                   f"{quote.as_of_date} against a previous close of "
                   f"{quote.prev_close:,.2f}. Threshold is "
                   f"{thresholds.watchlist_move_pct:.0f}%. "
                   f"Thesis on file: {reading.entry.thesis}",
            severity=_severity(abs(pct), thresholds.watchlist_move_pct),
            source_url=f"https://finance.yahoo.com/quote/{reading.entry.quote_symbol}",
        ))
    return alerts


def macro_alerts(readings: Iterable[MacroReading],
                 thresholds: AlertThresholds) -> list[Alert]:
    """Gold, copper, oil or AUD moving more than the daily threshold."""
    alerts = []
    for reading in readings:
        key = reading.metric.key
        if key in COMMODITY_METRICS:
            threshold, rule = thresholds.commodity_move_pct, "commodity_move"
        elif key in FX_METRICS:
            threshold, rule = thresholds.fx_move_pct, "fx_move"
        else:
            # A proxy series is not a price; it never raises an alert on its own.
            continue

        pct = reading.quote.pct_change
        if pct is None or abs(pct) <= threshold:
            continue

        alerts.append(Alert(
            rule=rule,
            subject=key,
            headline=f"{reading.metric.label} {_direction(pct)} {abs(pct):.1f}% "
                     f"to {reading.value:,.4g} {reading.metric.unit}",
            detail=f"Close for {reading.quote.as_of_date} against "
                   f"{reading.quote.prev_close:,.4g}. Threshold is {threshold:.0f}%. "
                   f"{reading.metric.note}",
            severity=_severity(abs(pct), threshold),
            source_url=reading.source_url,
        ))
    return alerts


def evaluate(watchlist: Iterable[WatchlistReading], macro: Iterable[MacroReading],
             thresholds: AlertThresholds, sydney_date: str) -> list[Alert]:
    """Run every price rule and stamp the results with the run's date."""
    raw = watchlist_alerts(watchlist, thresholds) + macro_alerts(macro, thresholds)
    ordered = sorted(raw, key=lambda a: (a.severity != "urgent", a.rule, a.subject))
    return [alert.with_context(sydney_date) for alert in ordered]


# ---------------------------------------------------------------------------
# Persistence and dedupe
# ---------------------------------------------------------------------------


def store_new_alerts(conn: sqlite3.Connection, run_id: int,
                     alerts: Iterable[Alert]) -> list[Alert]:
    """Persist alerts and return only the ones not already recorded.

    The return value is what drives the email. An alert already stored under the
    same dedupe key has been sent before and must not buzz a second time — the
    daily job is supposed to be silent unless something genuinely new happened.
    """
    fresh = []
    for alert in alerts:
        cur = conn.execute(
            "INSERT INTO alerts (run_id, fired_at, sydney_date, rule, subject, "
            "severity, headline, detail, source_url, emailed, dedupe_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?) "
            "ON CONFLICT (dedupe_key) DO NOTHING",
            (run_id, utc_now_iso(), alert.sydney_date, alert.rule, alert.subject,
             alert.severity, alert.headline, alert.detail, alert.source_url,
             alert.dedupe_key),
        )
        if cur.rowcount > 0:
            fresh.append(alert)
    conn.commit()
    return fresh


def mark_emailed(conn: sqlite3.Connection, alerts: Iterable[Alert]) -> None:
    keys = [alert.dedupe_key for alert in alerts]
    if not keys:
        return
    conn.executemany("UPDATE alerts SET emailed = 1 WHERE dedupe_key = ?",
                     [(key,) for key in keys])
    conn.commit()


def recent_alerts(conn: sqlite3.Connection, since_date: str) -> list[sqlite3.Row]:
    """Alerts since a date, for the weekly report's recap."""
    return list(conn.execute(
        "SELECT * FROM alerts WHERE sydney_date >= ? ORDER BY sydney_date DESC, id DESC",
        (since_date,)))
