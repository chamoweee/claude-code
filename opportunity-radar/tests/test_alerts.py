"""The alert rules decide whether a phone buzzes at 7am, so they are tested
hard: exact thresholds, no false positives, no duplicate sends.
"""

from __future__ import annotations

import pytest

from radar.alerts import rules
from radar.config import AlertThresholds, WatchlistEntry, load_settings
from radar.db import connect
from radar.runlog import start_run
from radar.sources.macro import METRICS_BY_KEY, MacroReading
from radar.sources.quotes import WatchlistReading
from radar.sources.yahoo import Bar, Quote

THRESHOLDS = AlertThresholds(watchlist_move_pct=8.0, commodity_move_pct=3.0,
                             fx_move_pct=3.0)


def make_quote(symbol: str, close: float, prev_close: float | None) -> Quote:
    history = [Bar("2026-09-15", prev_close)] if prev_close else []
    history.append(Bar("2026-09-16", close))
    return Quote(symbol=symbol, name=f"{symbol} Ltd", currency="AUD", exchange="ASX",
                 as_of_date="2026-09-16", close=close, prev_close=prev_close,
                 history=tuple(history))


def watch(symbol: str, close: float, prev_close: float | None) -> WatchlistReading:
    entry = WatchlistEntry(symbol=symbol, name=f"{symbol} Ltd", kind="equity",
                           exchange="ASX", quote_symbol=f"{symbol}.AX",
                           confirmed=True, active=True, thesis="test thesis")
    return WatchlistReading(entry=entry, quote=make_quote(symbol, close, prev_close))


def macro(key: str, close: float, prev_close: float | None) -> MacroReading:
    metric = METRICS_BY_KEY[key]
    return MacroReading(metric=metric, quote=make_quote(metric.symbol, close, prev_close))


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    yield connection
    connection.close()


# ---------------------------------------------------------------------------
# Watchlist rule: more than 8% in a day
# ---------------------------------------------------------------------------


def test_a_big_move_fires():
    alerts = rules.watchlist_alerts([watch("SDR", 110.0, 100.0)], THRESHOLDS)
    assert len(alerts) == 1
    assert alerts[0].rule == "watchlist_move"
    assert "rose 10.0%" in alerts[0].headline


def test_a_big_fall_fires_and_says_fell():
    alerts = rules.watchlist_alerts([watch("SDR", 90.0, 100.0)], THRESHOLDS)
    assert "fell 10.0%" in alerts[0].headline


def test_a_small_move_stays_silent():
    assert rules.watchlist_alerts([watch("SDR", 107.0, 100.0)], THRESHOLDS) == []


def test_the_threshold_is_exclusive():
    """Exactly 8.0% is not 'more than 8%'. The brief's wording is the spec."""
    assert rules.watchlist_alerts([watch("SDR", 108.0, 100.0)], THRESHOLDS) == []
    assert len(rules.watchlist_alerts([watch("SDR", 108.01, 100.0)], THRESHOLDS)) == 1


def test_no_previous_close_cannot_fire():
    assert rules.watchlist_alerts([watch("SDR", 100.0, None)], THRESHOLDS) == []


def test_severity_escalates_at_double_the_threshold():
    assert rules.watchlist_alerts([watch("SDR", 112.0, 100.0)], THRESHOLDS)[0].severity \
        == "notable"
    assert rules.watchlist_alerts([watch("SDR", 120.0, 100.0)], THRESHOLDS)[0].severity \
        == "urgent"


def test_the_alert_carries_the_thesis_so_the_email_is_actionable():
    alert = rules.watchlist_alerts([watch("SDR", 120.0, 100.0)], THRESHOLDS)[0]
    assert "test thesis" in alert.detail
    assert alert.source_url.endswith("SDR.AX")


# ---------------------------------------------------------------------------
# Macro rules: more than 3% on gold, copper, oil or AUD
# ---------------------------------------------------------------------------


def test_commodity_move_fires_at_its_own_threshold():
    alerts = rules.macro_alerts([macro("gold", 104.0, 100.0)], THRESHOLDS)
    assert len(alerts) == 1
    assert alerts[0].rule == "commodity_move"


def test_a_commodity_move_under_three_percent_is_silent():
    assert rules.macro_alerts([macro("gold", 102.0, 100.0)], THRESHOLDS) == []


def test_a_five_percent_commodity_move_would_not_fire_on_the_stock_threshold():
    """The 3% and 8% thresholds must not be crossed over."""
    alerts = rules.macro_alerts([macro("brent", 105.0, 100.0)], THRESHOLDS)
    assert len(alerts) == 1, "5% breaches the 3% commodity threshold"
    assert rules.watchlist_alerts([watch("SDR", 105.0, 100.0)], THRESHOLDS) == [], \
        "the same 5% must not breach the 8% stock threshold"


def test_fx_uses_the_fx_rule_name():
    alerts = rules.macro_alerts([macro("aud_usd", 0.74, 0.71)], THRESHOLDS)
    assert alerts[0].rule == "fx_move"
    assert alerts[0].subject == "aud_usd"


def test_the_uranium_proxy_never_raises_an_alert():
    """A miner ETF moving 10% is not a uranium price move, so it must stay quiet."""
    assert rules.macro_alerts([macro("uranium_ura_proxy", 110.0, 100.0)], THRESHOLDS) == []


def test_macro_alert_detail_carries_the_metric_caveat():
    alert = rules.macro_alerts([macro("gold", 104.0, 100.0)], THRESHOLDS)[0]
    assert "COMEX" in alert.detail, "the futures-vs-spot caveat must reach the email"


# ---------------------------------------------------------------------------
# Combining and ordering
# ---------------------------------------------------------------------------


def test_evaluate_combines_both_families_and_stamps_the_date():
    alerts = rules.evaluate([watch("SDR", 120.0, 100.0)], [macro("gold", 104.0, 100.0)],
                            THRESHOLDS, "2026-09-16")
    assert {a.rule for a in alerts} == {"watchlist_move", "commodity_move"}
    assert all(a.sydney_date == "2026-09-16" for a in alerts)
    assert all(a.dedupe_key for a in alerts)


def test_urgent_alerts_sort_first():
    alerts = rules.evaluate(
        [watch("AAA", 109.0, 100.0), watch("ZZZ", 130.0, 100.0)], [],
        THRESHOLDS, "2026-09-16")
    assert alerts[0].subject == "ZZZ" and alerts[0].severity == "urgent"


def test_a_quiet_day_produces_nothing():
    alerts = rules.evaluate([watch("SDR", 100.5, 100.0)], [macro("gold", 100.5, 100.0)],
                            THRESHOLDS, "2026-09-16")
    assert alerts == [], "a quiet day must send no email at all"


# ---------------------------------------------------------------------------
# Dedupe: the daily job must not buzz twice for one event
# ---------------------------------------------------------------------------


def test_only_new_alerts_come_back_for_emailing(conn):
    run = start_run(conn, "daily", "2026-09-16")
    alerts = rules.evaluate([watch("SDR", 120.0, 100.0)], [], THRESHOLDS, "2026-09-16")

    first = rules.store_new_alerts(conn, run.id, alerts)
    assert len(first) == 1, "the first sighting is emailable"

    second = rules.store_new_alerts(conn, run.id, alerts)
    assert second == [], "re-running the same day must not email again"
    assert conn.execute("SELECT COUNT(*) AS n FROM alerts").fetchone()["n"] == 1


def test_the_same_move_on_a_later_day_is_a_new_alert(conn):
    run = start_run(conn, "daily", "2026-09-16")
    today = rules.evaluate([watch("SDR", 120.0, 100.0)], [], THRESHOLDS, "2026-09-16")
    tomorrow = rules.evaluate([watch("SDR", 120.0, 100.0)], [], THRESHOLDS, "2026-09-17")
    assert len(rules.store_new_alerts(conn, run.id, today)) == 1
    assert len(rules.store_new_alerts(conn, run.id, tomorrow)) == 1


def test_mark_emailed_flags_the_rows(conn):
    run = start_run(conn, "daily", "2026-09-16")
    alerts = rules.evaluate([watch("SDR", 120.0, 100.0)], [], THRESHOLDS, "2026-09-16")
    fresh = rules.store_new_alerts(conn, run.id, alerts)
    rules.mark_emailed(conn, fresh)
    assert conn.execute("SELECT emailed FROM alerts").fetchone()["emailed"] == 1


def test_mark_emailed_handles_an_empty_list(conn):
    rules.mark_emailed(conn, [])  # must not raise


def test_recent_alerts_feed_the_weekly_recap(conn):
    run = start_run(conn, "daily", "2026-09-16")
    for date in ("2026-09-14", "2026-09-16"):
        rules.store_new_alerts(conn, run.id, rules.evaluate(
            [watch("SDR", 120.0, 100.0)], [], THRESHOLDS, date))
    assert len(rules.recent_alerts(conn, "2026-09-15")) == 1
    assert len(rules.recent_alerts(conn, "2026-09-01")) == 2


# ---------------------------------------------------------------------------
# The configured thresholds are the ones the brief asked for
# ---------------------------------------------------------------------------


def test_configured_thresholds_match_the_brief():
    alerts = load_settings().alerts
    assert alerts.watchlist_move_pct == 8.0
    assert alerts.commodity_move_pct == 3.0
    assert alerts.fx_move_pct == 3.0
