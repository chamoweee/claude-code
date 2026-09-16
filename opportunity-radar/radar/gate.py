"""The daylight-saving gate.

GitHub Actions cron only speaks UTC, and Sydney is UTC+10 for part of the year
and UTC+11 for the rest (AEDT starts 4 Oct 2026, and on the first Sunday of
October every year after). Rather than maintain a table of switch dates, both
workflows fire at *two* UTC times — 20:00 and 21:00 — and this module decides
whether the run that just woke up is actually the 7am Sydney one.

Exactly one of the two firings passes on any given day, whichever side of the
switch we are on. The other exits 0 without spending a cent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import Settings

WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class GateDecision:
    should_run: bool
    reason: str
    sydney_time: datetime

    @property
    def sydney_date(self) -> str:
        return self.sydney_time.date().isoformat()


def sydney_now(settings: Settings, now_utc: datetime | None = None) -> datetime:
    """Current wall-clock time in Sydney, derived from a UTC instant."""
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(ZoneInfo(settings.schedule.timezone))


def evaluate(kind: str, settings: Settings, now_utc: datetime | None = None,
             force: bool = False) -> GateDecision:
    """Decide whether a ``weekly`` or ``daily`` run should proceed right now."""
    local = sydney_now(settings, now_utc)
    sched = settings.schedule

    if force:
        return GateDecision(True, "forced via --force / RADAR_FORCE", local)

    if kind == "weekly":
        wanted_days = (sched.weekly_weekday,)
        wanted_hour = sched.weekly_hour
    elif kind == "daily":
        wanted_days = sched.daily_weekdays
        wanted_hour = sched.daily_hour
    else:
        raise ValueError(f"unknown run kind: {kind!r}")

    if local.weekday() not in wanted_days:
        expected = ", ".join(WEEKDAY_NAMES[d] for d in wanted_days)
        return GateDecision(
            False,
            f"{WEEKDAY_NAMES[local.weekday()]} in Sydney; {kind} runs on {expected}",
            local,
        )

    if local.hour != wanted_hour:
        return GateDecision(
            False,
            f"{local:%H:%M} in Sydney; {kind} runs in the {wanted_hour:02d}:00 hour "
            f"(the other UTC cron firing will pick it up)",
            local,
        )

    return GateDecision(
        True,
        f"{local:%a %d %b %H:%M} {local.tzname()} — inside the {kind} window",
        local,
    )


def next_run_after(kind: str, settings: Settings, now_utc: datetime | None = None) -> datetime:
    """The next Sydney datetime at which ``kind`` would run. Used by ``status``."""
    local = sydney_now(settings, now_utc)
    sched = settings.schedule
    wanted_days = (sched.weekly_weekday,) if kind == "weekly" else sched.daily_weekdays
    wanted_hour = sched.weekly_hour if kind == "weekly" else sched.daily_hour

    candidate = local.replace(hour=wanted_hour, minute=0, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    for _ in range(8):
        if candidate.weekday() in wanted_days:
            # Re-normalise: adding days across a DST switch can shift the hour.
            return candidate.replace(hour=wanted_hour, minute=0, second=0, microsecond=0)
        candidate += timedelta(days=1)
    raise RuntimeError(f"could not find a next {kind} run within 8 days")


def utc_firing_times(settings: Settings, kind: str,
                     now_utc: datetime | None = None) -> tuple[str, str]:
    """The two UTC HH:MM strings the cron should use, for documentation output."""
    nxt = next_run_after(kind, settings, now_utc)
    as_utc = nxt.astimezone(timezone.utc)
    # The pair is "this hour under AEDT" and "this hour under AEST", which are
    # one hour apart. Whichever season the next run falls in, the other firing
    # is on the far side: AEDT (UTC+11) fires earlier in UTC than AEST (UTC+10).
    other = (as_utc + timedelta(hours=1)) if nxt.dst() else (as_utc - timedelta(hours=1))
    pair = sorted([f"{as_utc:%H:%M}", f"{other:%H:%M}"])
    return pair[0], pair[1]
