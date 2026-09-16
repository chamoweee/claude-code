"""The two scheduled jobs, end to end, with nothing real behind them.

Prices come from recorded JSON, research from a fake SDK, and email through an
injected sender that records instead of sending. What is actually being tested
is the wiring: that the gate stops the wrong firing, that a quiet day sends
nothing, that a failure always reaches the inbox, and that hitting the budget
cap is a clean stop rather than a crash.
"""

from __future__ import annotations

import json

import pytest

from radar.config import load_settings
from radar.db import connect
from radar.jobs import common, daily, weekly
from radar.jobs.common import EXIT_FAILED, EXIT_OK
from radar.seed_baseline import seed
from radar.sources import macro as macro_mod
from radar.sources import quotes as quotes_mod

from .test_market import quote_from_fixture
from .test_research import (
    DISCOVERY_JSON,
    SYNTHESIS_JSON,
    THEME_JSON,
    FakeAnthropic,
    FakeMessage,
)

# 21:00 UTC Sunday is 07:00 Monday AEST — the firing that should run.
MONDAY_AEST = "2026-09-27T21:00:00+00:00"
WRONG_FIRING = "2026-09-27T20:00:00+00:00"


class Outbox:
    """Stands in for the Gmail sender and records what would have gone out.

    Deliberately not a list subclass: an empty one would be falsy, and that is
    exactly the trap that `common.send` must not fall into.
    """

    def __init__(self):
        self.messages: list[dict] = []

    def __call__(self, *, recipient, subject, html, text, **kwargs):
        self.messages.append({"recipient": recipient, "subject": subject,
                              "html": html, "text": text})
        return f"msg-{len(self.messages)}"

    def __len__(self):
        return len(self.messages)

    def __getitem__(self, index):
        return self.messages[index]

    def __eq__(self, other):
        return self.messages == other

    @property
    def subjects(self):
        return [item["subject"] for item in self.messages]


@pytest.fixture
def outbox():
    return Outbox()


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """No network, no real inbox, and a throwaway database."""
    monkeypatch.setenv("RADAR_DB", str(tmp_path / "radar.db"))
    monkeypatch.setenv("RADAR_RECIPIENT", "someone@example.com")
    monkeypatch.setenv("RADAR_PROFILE", "Test profile. Evenings and weekends only.")
    monkeypatch.delenv("RADAR_FORCE", raising=False)
    monkeypatch.setattr(macro_mod, "fetch_quote",
                        lambda symbol, **kw: quote_from_fixture("chart_GC_F.json", symbol))
    monkeypatch.setattr(quotes_mod, "fetch_quote",
                        lambda symbol, **kw: quote_from_fixture("chart_VICI.json", symbol))
    monkeypatch.setattr(common, "REPORTS_DIR", tmp_path / "reports", raising=False)


@pytest.fixture
def seeded(tmp_path):
    settings = load_settings(db_path=tmp_path / "radar.db")
    conn = connect(settings.db_path)
    seed(conn, settings)
    conn.close()
    return settings


def weekly_client(ctx):
    from radar.research.client import ResearchClient

    return ResearchClient(ctx.settings, ctx.guard, ctx.run,
                          client=FakeAnthropic(FakeMessage(THEME_JSON, searches=4),
                                               FakeMessage(DISCOVERY_JSON, searches=6),
                                               FakeMessage(SYNTHESIS_JSON)))


def daily_client(ctx, payload='{"alerts": []}'):
    from radar.research.client import ResearchClient

    return ResearchClient(ctx.settings, ctx.guard, ctx.run,
                          client=FakeAnthropic(FakeMessage(payload, searches=2)))


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_the_wrong_utc_firing_does_nothing(seeded, capsys):
    assert weekly.main(["--now", WRONG_FIRING]) == EXIT_OK
    assert "skip:" in capsys.readouterr().out


def test_the_right_firing_opens_a_run(seeded):
    ctx = common.open_job("weekly", now=_utc(MONDAY_AEST))
    assert ctx is not None
    assert ctx.sydney_date == "2026-09-28"
    ctx.conn.close()


def test_force_overrides_the_gate(seeded):
    ctx = common.open_job("weekly", now=_utc("2026-09-30T04:00:00+00:00"), force=True)
    assert ctx is not None
    ctx.conn.close()


def _utc(text):
    from datetime import datetime

    return datetime.fromisoformat(text)


# ---------------------------------------------------------------------------
# Weekly
# ---------------------------------------------------------------------------


def test_a_full_weekly_run_sends_one_report(seeded, outbox):
    ctx = common.open_job("weekly", now=_utc(MONDAY_AEST))
    assert weekly.run(ctx, client=weekly_client(ctx), sender=outbox) == EXIT_OK

    assert len(outbox) == 1
    assert outbox.subjects[0].startswith("Radar 2026-09-28:")
    assert "Battery rebate" in outbox[0]["html"]
    assert outbox[0]["recipient"] == "someone@example.com"
    ctx.conn.close()


def test_the_weekly_run_stores_everything_it_reported(seeded, outbox):
    ctx = common.open_job("weekly", now=_utc(MONDAY_AEST))
    weekly.run(ctx, client=weekly_client(ctx), sender=outbox)

    counts = {table: ctx.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
              for table in ("macro_snapshots", "watchlist_quotes", "opportunities",
                            "scores", "actions", "theme_updates", "spend", "reports")}
    assert counts["opportunities"] == 1
    assert counts["scores"] == 1
    assert counts["actions"] == 1
    assert counts["watchlist_quotes"] > 0
    assert counts["spend"] > 0
    assert counts["reports"] == 1
    ctx.conn.close()


def test_prices_are_stored_before_research_is_attempted(seeded, outbox, monkeypatch):
    """If research dies, the report must still carry real macro numbers."""
    ctx = common.open_job("weekly", now=_utc(MONDAY_AEST))
    from radar.research import engine

    monkeypatch.setattr(engine, "run_weekly",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        weekly.run(ctx, client=weekly_client(ctx), sender=outbox)

    stored = ctx.conn.execute("SELECT COUNT(*) AS n FROM macro_snapshots "
                              "WHERE as_of_date = '2026-09-28'").fetchone()["n"]
    assert stored > 0, "macro readings must survive a research failure"
    ctx.conn.close()


def test_a_quiet_week_still_sends(seeded, outbox):
    """A missing Monday email must mean something broke, not that nothing happened."""
    from radar.research.client import ResearchClient

    ctx = common.open_job("weekly", now=_utc(MONDAY_AEST))
    empty = ResearchClient(ctx.settings, ctx.guard, ctx.run, client=FakeAnthropic(
        FakeMessage('{"themes": []}'), FakeMessage('{"opportunities": []}'),
        FakeMessage('{"summary": ["Nothing moved."], "actions": []}')))
    assert weekly.run(ctx, client=empty, sender=outbox) == EXIT_OK
    assert len(outbox) == 1
    assert "Nothing moved" in outbox[0]["html"]
    assert "Macro snapshot" in outbox[0]["html"], "the quiet report is still complete"
    ctx.conn.close()


def test_dry_run_sends_nothing_but_still_stores(seeded, outbox):
    ctx = common.open_job("weekly", now=_utc(MONDAY_AEST), dry_run=True)
    assert weekly.run(ctx, client=weekly_client(ctx), sender=outbox) == EXIT_OK
    assert outbox == []
    assert ctx.conn.execute("SELECT COUNT(*) AS n FROM opportunities").fetchone()["n"] == 1
    ctx.conn.close()


def test_baseline_claims_retire_once_properly_sourced(seeded, outbox):
    ctx = common.open_job("weekly", now=_utc(MONDAY_AEST))
    before = ctx.conn.execute(
        "SELECT COUNT(*) AS n FROM evidence WHERE source_url LIKE 'baseline://%'"
    ).fetchone()["n"]
    weekly.run(ctx, client=weekly_client(ctx), sender=outbox)
    after = ctx.conn.execute(
        "SELECT COUNT(*) AS n FROM evidence WHERE source_url LIKE 'baseline://%'"
    ).fetchone()["n"]
    assert after < before
    ctx.conn.close()


def test_a_weekly_failure_emails_a_notice_and_exits_red(seeded, outbox, monkeypatch):
    from radar.research import engine

    monkeypatch.setattr(engine, "run_weekly",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("API down")))
    monkeypatch.setattr(common, "notify_failure",
                        lambda kind, date, errors, ctx=None, sender=None:
                        outbox(recipient="someone@example.com",
                               subject=f"Radar {kind} run failed — {date}",
                               html=str(errors), text=str(errors)))
    assert weekly.main(["--now", MONDAY_AEST]) == EXIT_FAILED
    assert len(outbox) == 1
    assert "run failed" in outbox.subjects[0]
    assert "API down" in outbox[0]["html"]


def test_a_failed_run_is_recorded_as_failed(seeded, monkeypatch, tmp_path):
    from radar.research import engine

    monkeypatch.setattr(engine, "run_weekly",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("API down")))
    monkeypatch.setattr(common, "notify_failure", lambda *a, **k: None)
    weekly.main(["--now", MONDAY_AEST])

    conn = connect(tmp_path / "radar.db")
    row = conn.execute("SELECT * FROM runs WHERE kind = 'weekly' "
                       "ORDER BY id DESC LIMIT 1").fetchone()
    assert row["status"] == "failed"
    assert "API down" in row["notes"]
    assert conn.execute("SELECT COUNT(*) AS n FROM run_events WHERE level = 'error'"
                        ).fetchone()["n"] > 0
    conn.close()


# ---------------------------------------------------------------------------
# Daily
# ---------------------------------------------------------------------------


def test_a_quiet_day_sends_nothing(seeded, outbox):
    ctx = common.open_job("daily", now=_utc(MONDAY_AEST))
    assert daily.run(ctx, client=daily_client(ctx), sender=outbox) == EXIT_OK
    assert outbox == [], "the daily job is silent unless something fired"
    ctx.conn.close()


def test_a_news_alert_sends_one_email(seeded, outbox):
    payload = json.dumps({"alerts": [{
        "rule": "rate_decision", "subject": "RBA", "headline": "RBA holds at 4.35%",
        "detail": "Held after three hikes.",
        "source_url": "https://www.rba.gov.au/media-releases/2026/mr-26-20.html",
        "source_date": "2026-09-28", "severity": "urgent"}]})
    ctx = common.open_job("daily", now=_utc(MONDAY_AEST))
    assert daily.run(ctx, client=daily_client(ctx, payload), sender=outbox) == EXIT_OK
    assert len(outbox) == 1
    assert outbox.subjects[0] == "Radar alert: RBA holds at 4.35%"
    ctx.conn.close()


def test_a_price_breach_fires_without_any_model_call(seeded, outbox, monkeypatch):
    """The threshold rules must work even when research is unavailable."""
    from radar.sources.yahoo import Bar, Quote

    big_move = Quote("VICI", "VICI", "USD", "NYSE", "2026-09-28", 120.0, 100.0,
                     (Bar("2026-09-25", 100.0), Bar("2026-09-28", 120.0)))
    monkeypatch.setattr(quotes_mod, "fetch_quote", lambda symbol, **kw: big_move)

    ctx = common.open_job("daily", now=_utc(MONDAY_AEST))
    monkeypatch.setattr(daily, "news_alerts", lambda ctx, client: ([], []))
    assert daily.run(ctx, client=None, sender=outbox) == EXIT_OK
    assert len(outbox) == 1
    assert "20.0%" in outbox[0]["html"]
    ctx.conn.close()


def test_the_same_alert_does_not_email_twice(seeded, outbox):
    payload = json.dumps({"alerts": [{
        "rule": "rate_decision", "subject": "RBA", "headline": "RBA holds at 4.35%",
        "detail": "Held.", "source_url": "https://www.rba.gov.au/mr.html",
        "source_date": "2026-09-28", "severity": "urgent"}]})

    ctx = common.open_job("daily", now=_utc(MONDAY_AEST))
    daily.run(ctx, client=daily_client(ctx, payload), sender=outbox)
    ctx.conn.close()

    ctx2 = common.open_job("daily", now=_utc(MONDAY_AEST))
    daily.run(ctx2, client=daily_client(ctx2, payload), sender=outbox)
    ctx2.conn.close()

    assert len(outbox) == 1, "a repeated event must not buzz the phone again"


def test_alerts_are_marked_emailed(seeded, outbox):
    payload = json.dumps({"alerts": [{
        "rule": "theme_news", "subject": "data-centres", "headline": "Firmus files",
        "detail": "Prospectus lodged.", "source_url": "https://www.asx.com.au/x",
        "source_date": "2026-09-28", "severity": "notable"}]})
    ctx = common.open_job("daily", now=_utc(MONDAY_AEST))
    daily.run(ctx, client=daily_client(ctx, payload), sender=outbox)
    assert ctx.conn.execute("SELECT emailed FROM alerts").fetchone()["emailed"] == 1
    ctx.conn.close()


def test_news_is_skipped_but_prices_still_run_when_the_budget_is_tight(
        seeded, outbox, monkeypatch):
    ctx = common.open_job("daily", now=_utc(MONDAY_AEST))
    ctx.conn.execute("INSERT INTO spend (at, month, model, cost_usd, cost_aud) VALUES "
                     "('2026-09-01T00:00:00+00:00', '2026-09', 'claude-sonnet-5', 20, 29.9)")
    ctx.conn.commit()

    alerts, failures = daily.news_alerts(ctx, daily_client(ctx))
    assert alerts == []
    assert "news check skipped" in failures[0]

    # The deterministic half is unaffected by the cap because it costs nothing.
    price, _ = daily.price_alerts(ctx)
    assert isinstance(price, list)
    ctx.conn.close()


# ---------------------------------------------------------------------------
# Budget halt
# ---------------------------------------------------------------------------


def test_hitting_the_cap_halts_cleanly_and_says_so_once(seeded, outbox, tmp_path):
    from radar.budget import BudgetExhausted

    ctx = common.open_job("weekly", now=_utc(MONDAY_AEST))
    exc = BudgetExhausted(30.5, 30.0, "2026-09")

    assert common.handle_budget_exhausted(exc, "weekly", ctx, sender=outbox) == EXIT_OK, \
        "halting is a rule working, not a failure — Actions should stay green"
    assert len(outbox) == 1
    assert "Radar halted" in outbox.subjects[0]
    assert "cap doing its job" in outbox[0]["html"]

    # A daily job that has hit the cap must not send this every weekday.
    assert common.handle_budget_exhausted(exc, "daily", ctx, sender=outbox) == EXIT_OK
    assert len(outbox) == 1, "the budget notice is sent once per month"
    assert ctx.conn.execute("SELECT status FROM runs ORDER BY id DESC LIMIT 1"
                            ).fetchone()["status"] == "budget_halted"
    ctx.conn.close()


# ---------------------------------------------------------------------------
# Email failure handling
# ---------------------------------------------------------------------------


def test_a_send_failure_is_logged_and_turns_the_run_red(seeded, monkeypatch):
    from radar.mail import gmail

    def broken(**kwargs):
        raise gmail.MailError("invalid_grant")

    ctx = common.open_job("weekly", now=_utc(MONDAY_AEST))
    assert weekly.run(ctx, client=weekly_client(ctx), sender=broken) == EXIT_FAILED
    assert any("email failed" in (e["detail"] or "") for e in ctx.run.errors())
    ctx.conn.close()


def test_notify_failure_never_raises(seeded, monkeypatch):
    """The last-resort path must survive anything, or a broken run goes silent."""
    def explode(**kwargs):
        raise RuntimeError("even the notice failed")

    common.notify_failure("weekly", "2026-09-28", ["original error"], sender=explode)


# ---------------------------------------------------------------------------
# Degradation: the cheap deterministic half must survive the expensive half
# ---------------------------------------------------------------------------


def test_a_price_breach_still_emails_when_the_news_check_dies(seeded, outbox, monkeypatch):
    """The 8% rule is the part that cannot wait. A broken research call must not
    swallow it — that would mean missing a real move because an API was down."""
    from radar.sources.yahoo import Bar, Quote

    big_move = Quote("VICI", "VICI", "USD", "NYSE", "2026-09-28", 120.0, 100.0,
                     (Bar("2026-09-25", 100.0), Bar("2026-09-28", 120.0)))
    monkeypatch.setattr(quotes_mod, "fetch_quote", lambda symbol, **kw: big_move)
    monkeypatch.setattr(daily, "news_alerts",
                        lambda ctx, client: (_ for _ in ()).throw(RuntimeError("API down")))

    ctx = common.open_job("daily", now=_utc(MONDAY_AEST))
    assert daily.run(ctx, client=None, sender=outbox) == EXIT_OK
    assert len(outbox) == 1, "the threshold alert must still reach the inbox"
    assert "20.0%" in outbox[0]["html"]
    assert any("news check failed" in (e["detail"] or "") for e in ctx.run.errors())
    ctx.conn.close()


def test_a_missing_api_key_is_an_actionable_message(seeded, monkeypatch):
    from radar.research.client import ResearchClient, ResearchError

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ctx = common.open_job("daily", now=_utc(MONDAY_AEST))
    with pytest.raises(ResearchError, match="ANTHROPIC_API_KEY is not set"):
        _ = ResearchClient(ctx.settings, ctx.guard, ctx.run).client
    ctx.conn.close()
