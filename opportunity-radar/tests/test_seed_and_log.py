"""Baseline seeding and run logging."""

from __future__ import annotations

import pytest

from radar import seed_baseline
from radar.config import load_settings, load_theme_seeds, load_watchlist
from radar.db import connect
from radar.runlog import last_run, run_scope, start_run


@pytest.fixture
def settings(tmp_path):
    return load_settings(db_path=tmp_path / "test.db")


@pytest.fixture
def conn(settings):
    connection = connect(settings.db_path)
    yield connection
    connection.close()


# --- seeding ----------------------------------------------------------------


def test_seed_writes_the_baseline(conn, settings):
    counts = seed_baseline.seed(conn, settings)
    assert counts["themes"] == 7, "the brief lists seven tracked themes"
    assert counts["macro"] == len(seed_baseline.BASELINE_MACRO)
    assert counts["evidence"] > 0
    assert counts["theme_updates"] == 7


def test_seed_is_idempotent(conn, settings):
    seed_baseline.seed(conn, settings)
    before = conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]
    second = seed_baseline.seed(conn, settings)
    after = conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]
    assert second == {"themes": 0, "macro": 0, "evidence": 0, "theme_updates": 0}
    assert after == before, "re-seeding must not duplicate evidence"


def test_force_reseed_replaces_rather_than_duplicates(conn, settings):
    seed_baseline.seed(conn, settings)
    before = conn.execute("SELECT COUNT(*) AS n FROM themes").fetchone()["n"]
    seed_baseline.seed(conn, settings, force=True)
    assert conn.execute("SELECT COUNT(*) AS n FROM themes").fetchone()["n"] == before


def test_baseline_macro_carries_the_brief_figures(conn, settings):
    seed_baseline.seed(conn, settings)
    rows = {r["metric"]: r for r in conn.execute("SELECT * FROM macro_snapshots")}
    assert rows["brent"]["value"] == pytest.approx(108.0)
    assert rows["gold"]["value"] == pytest.approx(4290.0)
    assert rows["rba_cash_rate"]["value"] == pytest.approx(4.35)
    assert rows["sydney_vacancy_rate"]["value"] == pytest.approx(2.2)
    # Copper arrived as a y/y change with no level, so it stays non-numeric.
    assert rows["copper"]["value"] is None
    assert "+38%" in rows["copper"]["value_text"]


def test_every_baseline_figure_is_marked_weak(conn, settings):
    """Our own starting numbers get no free pass: unsourced means weak."""
    seed_baseline.seed(conn, settings)
    strengths = {r["source_strength"] for r in conn.execute(
        "SELECT source_strength FROM macro_snapshots")}
    assert strengths == {"weak"}
    strengths = {r["source_strength"] for r in conn.execute(
        "SELECT source_strength FROM evidence")}
    assert strengths == {"weak"}


def test_unverified_claims_are_listable(conn, settings):
    seed_baseline.seed(conn, settings)
    gaps = seed_baseline.unverified_baseline_claims(conn)
    assert len(gaps) > 5
    assert all(row["claim"] for row in gaps)


def test_seed_run_is_recorded(conn, settings):
    seed_baseline.seed(conn, settings)
    row = last_run(conn, "seed")
    assert row["status"] == "ok"
    assert row["sydney_date"] == settings.baseline_date
    assert row["finished_at"] is not None


# --- run logging ------------------------------------------------------------


def test_run_scope_marks_failure_and_reraises(conn):
    with pytest.raises(ZeroDivisionError):
        with run_scope(conn, "weekly", "2026-09-21") as run:
            run.log_query("brent crude price", purpose="macro")
            _ = 1 / 0

    row = last_run(conn, "weekly")
    assert row["status"] == "failed"
    assert "ZeroDivisionError" in row["notes"]


def test_a_failed_run_still_keeps_its_trail(conn):
    with pytest.raises(RuntimeError):
        with run_scope(conn, "daily", "2026-09-22") as run:
            run.log_source("https://www.rba.gov.au/", "RBA", "primary")
            raise RuntimeError("web search unavailable")

    events = conn.execute(
        "SELECT event FROM run_events ORDER BY id").fetchall()
    kinds = [e["event"] for e in events]
    assert "source" in kinds and "error" in kinds


def test_run_scope_marks_success(conn):
    with run_scope(conn, "daily", "2026-09-22") as run:
        run.log("fetch", {"symbols": 7})
    assert last_run(conn, "daily")["status"] == "ok"


def test_sources_are_deduplicated(conn):
    run = start_run(conn, "weekly", "2026-09-21")
    run.log_source("https://www.rba.gov.au/", "RBA", "primary")
    run.log_source("https://www.rba.gov.au/", "RBA", "primary")
    run.log_source("https://www.abs.gov.au/", "ABS", "primary")
    assert len(run.sources()) == 2


def test_errors_are_retrievable_for_the_notice_email(conn):
    run = start_run(conn, "weekly", "2026-09-21")
    run.log_error("quote fetch failed", ValueError("bad symbol"))
    errors = run.errors()
    assert len(errors) == 1
    assert "bad symbol" in errors[0]["detail"]


# --- config sanity ----------------------------------------------------------


def test_watchlist_covers_the_brief(settings):
    symbols = {w.symbol for w in load_watchlist()}
    assert symbols == {"VVLU", "VLUE", "HVLU", "SDR", "AMC", "SCG", "CCL", "EG", "VICI", "LEN"}


def test_unquotable_tickers_cannot_be_silently_priced(settings):
    """Whatever the reason an entry is unquotable — ambiguous or delisted — it must
    carry no quote symbol, so no code path can price it against the wrong security."""
    for entry in load_watchlist():
        if entry.quotable:
            continue
        assert not entry.quote_symbol, (
            f"{entry.symbol} is not quotable but still has quote_symbol="
            f"{entry.quote_symbol!r}")


def test_theme_seeds_have_status_and_watch_for(settings):
    for theme in load_theme_seeds():
        assert theme.status in {"NEW", "RISING", "STABLE", "FADING", "DEAD"}
        assert theme.watch_for.strip(), f"{theme.slug} needs a watch_for"


def test_weak_evidence_theme_is_seeded_as_fading(settings):
    themes = {t.slug: t for t in load_theme_seeds()}
    assert themes["ai-automation-services"].status == "FADING", \
        "the brief marks this one weak evidence"
