"""Assembling a report from history.

Rendering reads the database rather than the research objects wherever it can,
so the email reflects what was actually stored. If a value never made it to
disk, it should not appear in the report either.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..budget import BudgetGuard
from ..sources.macro import METRICS_BY_KEY, MetricChange
from .render import ReportData


# Metrics that arrive from research or the baseline rather than the price
# registry, so METRICS_BY_KEY has no label for them.
EXTRA_LABELS = {
    "rba_cash_rate": "RBA cash rate",
    "fed_decision": "US Federal Reserve",
    "sydney_vacancy_rate": "Sydney rental vacancy",
    "cpi_au": "Australian CPI",
    "cpi_us": "US CPI",
}


def label_for(metric_key: str) -> str:
    metric = METRICS_BY_KEY.get(metric_key)
    if metric:
        return metric.label
    return EXTRA_LABELS.get(metric_key, metric_key.replace("_", " ").capitalize())


def macro_changes_from_history(conn: sqlite3.Connection, as_of_date: str) -> list[MetricChange]:
    """Latest reading per metric, against the most recent earlier one."""
    latest = conn.execute(
        "SELECT metric, MAX(as_of_date) AS d FROM macro_snapshots "
        "WHERE as_of_date <= ? AND value IS NOT NULL GROUP BY metric", (as_of_date,)
    ).fetchall()

    changes = []
    for row in latest:
        metric_key, latest_date = row["metric"], row["d"]
        current = conn.execute(
            "SELECT value, unit FROM macro_snapshots WHERE metric = ? AND as_of_date = ?",
            (metric_key, latest_date)).fetchone()
        previous = conn.execute(
            "SELECT value, as_of_date FROM macro_snapshots WHERE metric = ? "
            "AND as_of_date < ? AND value IS NOT NULL ORDER BY as_of_date DESC LIMIT 1",
            (metric_key, latest_date)).fetchone()

        metric = METRICS_BY_KEY.get(metric_key)
        changes.append(MetricChange(
            metric=metric_key,
            label=label_for(metric_key),
            unit=current["unit"] or (metric.unit if metric else ""),
            latest=float(current["value"]),
            previous=float(previous["value"]) if previous else None,
            previous_date=previous["as_of_date"] if previous else None,
            is_proxy=bool(metric.is_proxy) if metric else False,
        ))
    return sorted(changes, key=lambda c: c.label)


def theme_rows(conn: sqlite3.Connection, as_of_date: str) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT t.slug, t.title, u.status, u.reason, u.prev_status "
        "FROM theme_updates u JOIN themes t ON t.id = u.theme_id "
        "WHERE u.as_of_date = ? ORDER BY "
        "CASE u.status WHEN 'NEW' THEN 0 WHEN 'RISING' THEN 1 WHEN 'FADING' THEN 2 "
        "WHEN 'DEAD' THEN 3 ELSE 4 END, t.slug", (as_of_date,)).fetchall()
    if not rows:
        # No update this week: fall back to each theme's standing status.
        rows = conn.execute(
            "SELECT slug, title, status, '' AS reason, NULL AS prev_status "
            "FROM themes WHERE active = 1 ORDER BY slug").fetchall()
    out = []
    for row in rows:
        reason = row["reason"] or "No update this week."
        if row["prev_status"] and row["prev_status"] != row["status"]:
            reason = f"({row['prev_status']} → {row['status']}) {reason}"
        out.append({"slug": row["slug"], "title": row["title"],
                    "status": row["status"], "reason": reason})
    return out


def watchlist_rows(conn: sqlite3.Connection, as_of_date: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT symbol, MAX(as_of_date) AS d FROM watchlist_quotes "
        "WHERE as_of_date <= ? GROUP BY symbol ORDER BY symbol", (as_of_date,)).fetchall()
    out = []
    for row in rows:
        quote = conn.execute(
            "SELECT * FROM watchlist_quotes WHERE symbol = ? AND as_of_date = ?",
            (row["symbol"], row["d"])).fetchone()
        out.append({
            "symbol": quote["symbol"], "close": quote["close"],
            "currency": quote["currency"], "pct_change": quote["pct_change"],
            "note": f"close for {quote['as_of_date']}",
        })
    return out


def build_weekly(conn: sqlite3.Connection, settings, run, weekly, sydney_date: str,
                 guard: BudgetGuard | None = None) -> ReportData:
    guard = guard or BudgetGuard(conn, settings, sydney_date, run_id=run.id)
    alerts = conn.execute(
        "SELECT * FROM alerts WHERE sydney_date >= date(?, '-7 days') "
        "ORDER BY sydney_date DESC, id DESC LIMIT 20", (sydney_date,)).fetchall()

    return ReportData(
        sydney_date=sydney_date,
        summary=list(weekly.result.summary),
        macro=macro_changes_from_history(conn, sydney_date),
        themes=theme_rows(conn, sydney_date),
        actionable=list(weekly.actionable),
        other_leads=list(weekly.other),
        watchlist=watchlist_rows(conn, sydney_date),
        alerts=[_row_to_alert(row) for row in alerts],
        actions=list(weekly.result.actions),
        spend_status=guard.status(),
        spend_breakdown=guard.month_breakdown(),
        sources=run.sources(),
        rejected=list(weekly.result.rejected),
        failures=list(weekly.failures),
        budget_warning=guard.warning() or "",
    )


class _AlertView:
    """A stored alert row in the shape the renderer expects."""

    def __init__(self, row: sqlite3.Row):
        self.headline = row["headline"]
        self.detail = row["detail"] or ""
        self.severity = row["severity"]
        self.source_url = row["source_url"] or ""


def _row_to_alert(row: sqlite3.Row) -> _AlertView:
    return _AlertView(row)
