"""Price sources: the Yahoo parser, macro metrics and watchlist quotes.

Every test runs against recorded JSON in ``tests/fixtures/``. Nothing here
touches the network, so the suite is deterministic and runnable offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from radar.config import WatchlistEntry, load_settings, load_watchlist
from radar.db import connect
from radar.runlog import start_run
from radar.sources import macro as macro_mod
from radar.sources import quotes as quotes_mod
from radar.sources.http import FetchError
from radar.sources.yahoo import Bar, Quote, QuoteError, parse_chart

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def quote_from_fixture(name: str, symbol: str) -> Quote:
    return parse_chart(load_fixture(name), symbol)


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def run(conn):
    return start_run(conn, "daily", "2026-09-16")


@pytest.fixture
def settings():
    return load_settings()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parses_a_us_equity():
    quote = quote_from_fixture("chart_VICI.json", "VICI")
    assert quote.currency == "USD"
    assert quote.exchange == "NYSE"
    assert quote.close > 0
    assert quote.prev_close > 0
    assert len(quote.history) > 5


def test_parses_an_asx_equity_in_aud():
    quote = quote_from_fixture("chart_AMC_AX.json", "AMC.AX")
    assert quote.currency == "AUD"
    assert quote.exchange == "ASX"


def test_dates_come_from_the_exchange_timezone_not_ours():
    """An ASX close and a NYSE close on the same morning are different days.

    Dating both by the local Sydney date would silently corrupt day-on-day
    changes for the US half of the watchlist.
    """
    asx = quote_from_fixture("chart_AMC_AX.json", "AMC.AX")
    nyse = quote_from_fixture("chart_VICI.json", "VICI")
    assert asx.as_of_date > nyse.as_of_date, (
        "captured in one fetch, so the ASX date must lead the NYSE date")


def test_history_is_sorted_ascending():
    quote = quote_from_fixture("chart_GC_F.json", "GC=F")
    dates = [bar.date for bar in quote.history]
    assert dates == sorted(dates)


def test_pct_change_matches_the_last_two_closes():
    quote = quote_from_fixture("chart_EG.json", "EG")
    expected = (quote.close - quote.prev_close) / quote.prev_close * 100
    assert quote.pct_change == pytest.approx(expected)


def test_close_on_or_before_finds_the_week_ago_bar():
    quote = quote_from_fixture("chart_AUDUSD_X.json", "AUDUSD=X")
    target = quote.history[5].date
    assert quote.close_on_or_before(target).date == target
    # A date before any bar has nothing to return.
    assert quote.close_on_or_before("1990-01-01") is None


def test_null_closes_are_dropped_not_zeroed():
    """Non-trading days arrive as nulls; treating them as 0 would fake a -100% move."""
    payload = {"chart": {"result": [{
        "meta": {"currency": "USD", "exchangeTimezoneName": "America/New_York"},
        "timestamp": [1757500000, 1757600000, 1757700000],
        "indicators": {"quote": [{"close": [10.0, None, 11.0]}]},
    }]}}
    quote = parse_chart(payload, "TEST")
    assert len(quote.history) == 2
    assert quote.pct_change == pytest.approx(10.0)


def test_zero_closes_are_dropped():
    payload = {"chart": {"result": [{
        "meta": {"currency": "USD", "exchangeTimezoneName": "UTC"},
        "timestamp": [1757500000, 1757600000],
        "indicators": {"quote": [{"close": [0.0, 11.0]}]},
    }]}}
    assert len(parse_chart(payload, "TEST").history) == 1


def test_api_error_becomes_a_quote_error():
    payload = {"chart": {"result": None,
                         "error": {"code": "Not Found", "description": "No data"}}}
    with pytest.raises(QuoteError, match="Not Found"):
        parse_chart(payload, "EG.AX")


def test_empty_result_becomes_a_quote_error():
    with pytest.raises(QuoteError, match="no result"):
        parse_chart({"chart": {"result": []}}, "NOPE")


def test_all_null_closes_becomes_a_quote_error():
    payload = {"chart": {"result": [{
        "meta": {"exchangeTimezoneName": "UTC"},
        "timestamp": [1757500000],
        "indicators": {"quote": [{"close": [None]}]},
    }]}}
    with pytest.raises(QuoteError, match="no usable closes"):
        parse_chart(payload, "NOPE")


def test_single_bar_has_no_previous_close():
    payload = {"chart": {"result": [{
        "meta": {"exchangeTimezoneName": "UTC"},
        "timestamp": [1757500000],
        "indicators": {"quote": [{"close": [42.0]}]},
    }]}}
    quote = parse_chart(payload, "ONE")
    assert quote.prev_close is None
    assert quote.pct_change is None, "no prior close must mean no change, not zero"


# ---------------------------------------------------------------------------
# Macro
# ---------------------------------------------------------------------------


FIXTURE_FOR_METRIC = {
    "BZ=F": "chart_GC_F.json",        # shape is identical; values are irrelevant here
    "GC=F": "chart_GC_F.json",
    "HG=F": "chart_GC_F.json",
    "AUDUSD=X": "chart_AUDUSD_X.json",
    "URA": "chart_VICI.json",
}


def fake_macro_fetcher(symbol: str) -> Quote:
    return quote_from_fixture(FIXTURE_FOR_METRIC[symbol], symbol)


def test_macro_fetches_every_registered_metric(run):
    readings, failures = macro_mod.fetch_macro(run, fetcher=fake_macro_fetcher)
    assert len(readings) == len(macro_mod.METRICS)
    assert failures == []


def test_one_bad_metric_does_not_lose_the_others(run):
    def flaky(symbol: str) -> Quote:
        if symbol == "HG=F":
            raise FetchError(symbol, 3, TimeoutError("timed out"))
        return fake_macro_fetcher(symbol)

    readings, failures = macro_mod.fetch_macro(run, fetcher=flaky)
    assert len(readings) == len(macro_mod.METRICS) - 1
    assert len(failures) == 1 and "Copper" in failures[0]
    assert len(run.errors()) == 1, "the failure is logged, not swallowed"


def test_uranium_is_registered_as_a_proxy():
    """URA is a miner ETF, not a uranium price. Mislabelling it would be a lie."""
    metric = macro_mod.METRICS_BY_KEY["uranium_ura_proxy"]
    assert metric.is_proxy
    assert "NOT a uranium price" in metric.note


def test_stored_proxy_rows_are_labelled_in_the_database(conn, run):
    readings, _ = macro_mod.fetch_macro(run, fetcher=fake_macro_fetcher)
    macro_mod.store_macro(conn, run.id, "2026-09-16", readings)
    row = conn.execute(
        "SELECT note FROM macro_snapshots WHERE metric = 'uranium_ura_proxy'").fetchone()
    assert row["note"].startswith("PROXY — ")


def test_storing_twice_on_one_day_updates_rather_than_duplicates(conn, run):
    readings, _ = macro_mod.fetch_macro(run, fetcher=fake_macro_fetcher)
    macro_mod.store_macro(conn, run.id, "2026-09-16", readings)
    macro_mod.store_macro(conn, run.id, "2026-09-16", readings)
    count = conn.execute("SELECT COUNT(*) AS n FROM macro_snapshots").fetchone()["n"]
    assert count == len(macro_mod.METRICS)


def test_week_on_week_change_is_computed_against_the_prior_snapshot(conn, run):
    conn.execute(
        "INSERT INTO macro_snapshots (as_of_date, metric, value, unit, source_strength) "
        "VALUES ('2026-09-09', 'gold', 4000.0, 'USD/oz', 'reputable_media')")
    conn.commit()
    readings, _ = macro_mod.fetch_macro(run, fetcher=fake_macro_fetcher)
    changes = {c.metric: c for c in
               macro_mod.changes_since_last_snapshot(conn, "2026-09-16", readings)}
    gold = changes["gold"]
    assert gold.previous == pytest.approx(4000.0)
    assert gold.previous_date == "2026-09-09"
    assert gold.pct_change == pytest.approx((gold.latest - 4000.0) / 4000.0 * 100)
    assert gold.format_change().startswith(("+", "-"))


def test_a_metric_with_no_history_says_so_rather_than_showing_zero(conn, run):
    readings, _ = macro_mod.fetch_macro(run, fetcher=fake_macro_fetcher)
    changes = {c.metric: c for c in
               macro_mod.changes_since_last_snapshot(conn, "2026-09-16", readings)}
    assert changes["brent"].pct_change is None
    assert changes["brent"].format_change() == "no prior reading"
    assert changes["brent"].direction == "new"


def test_usd_to_aud_is_the_reciprocal_of_aud_usd(run):
    readings, _ = macro_mod.fetch_macro(run, fetcher=fake_macro_fetcher)
    aud = next(r for r in readings if r.metric.key == "aud_usd")
    rate = macro_mod.usd_to_aud_from(readings)
    assert rate == pytest.approx(1.0 / aud.value)
    assert 1.0 < rate < 2.5, "a plausible USD->AUD rate"


def test_usd_to_aud_is_none_without_an_fx_reading():
    assert macro_mod.usd_to_aud_from([]) is None


def test_configured_fx_rate_is_close_to_the_live_one(settings, run):
    """Guards against the committed default drifting far from reality."""
    readings, _ = macro_mod.fetch_macro(run, fetcher=fake_macro_fetcher)
    live = macro_mod.usd_to_aud_from(readings)
    drift = abs(settings.budget.usd_to_aud - live) / live
    assert drift < 0.05, (
        f"config usd_to_aud={settings.budget.usd_to_aud} is {drift:.0%} from the "
        f"fixture rate {live:.4f}; API costs would be misreported")


# ---------------------------------------------------------------------------
# Watchlist quotes
# ---------------------------------------------------------------------------


def entry(symbol: str, quote_symbol: str = "", *, confirmed: bool = True,
          active: bool = True) -> WatchlistEntry:
    return WatchlistEntry(symbol=symbol, name=f"{symbol} Inc", kind="equity",
                          exchange="NYSE", quote_symbol=quote_symbol or symbol,
                          confirmed=confirmed, active=active, thesis="test")


def fake_quote_fetcher(symbol: str) -> Quote:
    return quote_from_fixture("chart_VICI.json", symbol)


def test_unconfirmed_tickers_are_skipped_not_guessed(run):
    entries = [entry("VICI"), entry("MYSTERY", "", confirmed=False)]
    readings, skipped, failures = quotes_mod.fetch_watchlist(
        run, entries, fetcher=fake_quote_fetcher)
    assert [r.entry.symbol for r in readings] == ["VICI"]
    assert [s.symbol for s in skipped] == ["MYSTERY"]
    assert "not resolved" in skipped[0].reason
    assert failures == []


def test_delisted_tickers_are_skipped_with_their_own_reason(run):
    readings, skipped, _ = quotes_mod.fetch_watchlist(
        run, [entry("CCL", "", active=False)], fetcher=fake_quote_fetcher)
    assert readings == []
    assert skipped[0].reason == "no longer trading"


def test_the_real_watchlist_is_fully_resolved_now():
    """HVLU, CCL and EG were unresolved in Stage 1. Only CCL should remain unquotable."""
    entries = {w.symbol: w for w in load_watchlist()}
    assert all(w.confirmed for w in entries.values()), "no ticker should still be ambiguous"
    unquotable = {s for s, w in entries.items() if not w.quotable}
    assert unquotable == {"CCL"}, "CCL is delisted; everything else must be quotable"
    assert entries["HVLU"].quote_symbol == "HVLU.AX"
    assert entries["EG"].quote_symbol == "EG"


def test_a_failed_quote_does_not_lose_the_rest(run):
    def flaky(symbol: str) -> Quote:
        if symbol == "BROKEN":
            raise QuoteError("BROKEN: no usable closes")
        return fake_quote_fetcher(symbol)

    readings, _, failures = quotes_mod.fetch_watchlist(
        run, [entry("VICI"), entry("BROKEN"), entry("LEN")], fetcher=flaky)
    assert [r.entry.symbol for r in readings] == ["VICI", "LEN"]
    assert len(failures) == 1


def test_quotes_are_stored_against_the_exchange_date(conn, run):
    readings, _, _ = quotes_mod.fetch_watchlist(run, [entry("VICI")],
                                                fetcher=fake_quote_fetcher)
    quotes_mod.store_quotes(conn, run.id, readings)
    row = conn.execute("SELECT * FROM watchlist_quotes").fetchone()
    assert row["as_of_date"] == readings[0].quote.as_of_date
    assert row["currency"] == "USD"
    assert row["pct_change"] == pytest.approx(readings[0].quote.pct_change)


def test_restoring_the_same_day_updates_in_place(conn, run):
    readings, _, _ = quotes_mod.fetch_watchlist(run, [entry("VICI")],
                                                fetcher=fake_quote_fetcher)
    quotes_mod.store_quotes(conn, run.id, readings)
    quotes_mod.store_quotes(conn, run.id, readings)
    assert conn.execute("SELECT COUNT(*) AS n FROM watchlist_quotes").fetchone()["n"] == 1


def test_change_since_compares_against_an_earlier_close(conn):
    for date, close in (("2026-09-07", 100.0), ("2026-09-14", 110.0)):
        conn.execute(
            "INSERT INTO watchlist_quotes (symbol, as_of_date, close) VALUES (?, ?, ?)",
            ("VICI", date, close))
    conn.commit()
    assert quotes_mod.change_since(conn, "VICI", "2026-09-08") == pytest.approx(10.0)


def test_change_since_returns_none_with_nothing_to_compare(conn):
    conn.execute("INSERT INTO watchlist_quotes (symbol, as_of_date, close) "
                 "VALUES ('VICI', '2026-09-14', 110.0)")
    conn.commit()
    assert quotes_mod.change_since(conn, "VICI", "2026-09-08") is None, \
        "one data point must report no change, not a zero change"
    assert quotes_mod.change_since(conn, "NOSUCH", "2026-09-08") is None
