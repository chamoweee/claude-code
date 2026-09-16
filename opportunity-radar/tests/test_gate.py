"""The daylight-saving gate is the part most likely to fail silently, so it gets
the most tests. Sydney switches to AEDT on 4 Oct 2026; these cases straddle it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from radar import gate
from radar.config import load_settings


@pytest.fixture(scope="module")
def settings():
    return load_settings()


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


# --- the two cron firings, either side of the switch ------------------------


@pytest.mark.parametrize(
    "instant, expect_run, note",
    [
        # AEST (UTC+10): 7am Sydney Monday 28 Sep == 21:00 UTC Sunday 27 Sep.
        ("2026-09-27T21:00", True, "AEST firing runs"),
        ("2026-09-27T20:00", False, "the 20:00 firing is 6am Sydney under AEST"),
        # AEDT (UTC+11): 7am Sydney Monday 5 Oct == 20:00 UTC Sunday 4 Oct.
        ("2026-10-04T20:00", True, "AEDT firing runs"),
        ("2026-10-04T21:00", False, "the 21:00 firing is 8am Sydney under AEDT"),
    ],
)
def test_weekly_gate_across_the_dst_switch(settings, instant, expect_run, note):
    decision = gate.evaluate("weekly", settings, utc(instant))
    assert decision.should_run is expect_run, f"{note}: {decision.reason}"


def test_exactly_one_firing_passes_each_monday(settings):
    """Whatever the season, one of the two crons runs and the other does not."""
    # Sundays either side of both switches: AEDT starts 4 Oct 2026, ends 4 Apr 2027.
    for sunday in ("2026-09-27", "2026-10-04", "2027-01-10", "2027-04-04", "2027-06-27"):
        passed = [h for h in (20, 21)
                  if gate.evaluate("weekly", settings, utc(f"{sunday}T{h}:00")).should_run]
        assert len(passed) == 1, f"{sunday}: {len(passed)} firings passed, expected exactly 1"


# --- day-of-week handling ---------------------------------------------------


def test_weekly_does_not_run_on_a_tuesday(settings):
    decision = gate.evaluate("weekly", settings, utc("2026-09-28T21:00"))
    assert not decision.should_run
    assert "Monday" in decision.reason


def test_daily_runs_on_weekdays_but_not_weekends(settings):
    # 21:00 UTC Sun 27 Sep -> Mon 28 Sep 07:00 Sydney: a weekday.
    assert gate.evaluate("daily", settings, utc("2026-09-27T21:00")).should_run
    # 21:00 UTC Fri 2 Oct -> Sat 3 Oct 07:00 Sydney: a weekend.
    assert not gate.evaluate("daily", settings, utc("2026-10-02T21:00")).should_run


def test_force_overrides_everything(settings):
    decision = gate.evaluate("weekly", settings, utc("2026-09-30T03:17"), force=True)
    assert decision.should_run
    assert "forced" in decision.reason


def test_unknown_kind_is_rejected(settings):
    with pytest.raises(ValueError):
        gate.evaluate("hourly", settings, utc("2026-09-27T21:00"))


# --- the derived values `status` prints -------------------------------------


def test_next_run_lands_on_monday_at_seven(settings):
    nxt = gate.next_run_after("weekly", settings, utc("2026-09-29T04:00"))
    assert nxt.weekday() == 0
    assert (nxt.hour, nxt.minute) == (7, 0)
    assert nxt > gate.sydney_now(settings, utc("2026-09-29T04:00"))


def test_next_run_keeps_seven_am_across_the_switch(settings):
    """Adding days across the DST boundary must not drift the local hour."""
    nxt = gate.next_run_after("weekly", settings, utc("2026-10-01T04:00"))
    assert nxt.hour == 7
    assert nxt.tzname() == "AEDT", "5 Oct 2026 is after the switch"


def test_utc_firing_times_are_the_two_cron_hours(settings):
    assert gate.utc_firing_times(settings, "weekly", utc("2026-09-29T04:00")) == ("20:00", "21:00")


def test_sydney_now_accepts_a_naive_instant_as_utc(settings):
    aware = gate.sydney_now(settings, utc("2026-09-27T21:00"))
    naive = gate.sydney_now(settings, datetime(2026, 9, 27, 21, 0))
    assert aware == naive
