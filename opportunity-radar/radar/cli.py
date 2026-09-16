"""Command line entry point.

    python -m radar.cli status          # what the agent knows and what it will cost
    python -m radar.cli seed            # write the 16 Sep 2026 baseline snapshot
    python -m radar.cli gate weekly     # would a run fire right now?
    python -m radar.cli prices          # live macro + watchlist fetch, free
    python -m radar.cli baseline-gaps   # baseline claims still lacking a real source

No command here calls the Claude API, so none of them costs anything. Only
`prices` touches the network.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from . import budget as budget_mod
from . import gate as gate_mod
from . import seed_baseline
from .config import (
    ConfigError,
    load_recipient,
    load_settings,
    load_watchlist,
    profile_is_real,
)
from .db import SCHEMA_VERSION, connect, table_counts
from .runlog import start_run


def _parse_now(value: str | None) -> datetime | None:
    """``--now`` accepts a UTC ISO-8601 instant, for testing the gate by hand."""
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def cmd_status(args: argparse.Namespace) -> int:
    settings = load_settings()
    now = _parse_now(args.now)
    local = gate_mod.sydney_now(settings, now)
    conn = connect(settings.db_path)

    print("Opportunity Radar — status")
    print(f"  Sydney now       {local:%a %d %b %Y %H:%M} {local.tzname()} "
          f"(UTC{local.utcoffset().total_seconds() / 3600:+.0f})")
    print(f"  Database         {settings.db_path} (schema v{SCHEMA_VERSION})")

    counts = table_counts(conn)
    interesting = ("runs", "macro_snapshots", "themes", "theme_updates",
                   "opportunities", "evidence", "scores", "watchlist_quotes",
                   "alerts", "actions", "spend")
    print("  History          " + ", ".join(f"{n}={counts.get(n, 0)}" for n in interesting))

    # --- schedule ---------------------------------------------------------
    print("\nSchedule (daylight-saving safe)")
    for kind in ("weekly", "daily"):
        nxt = gate_mod.next_run_after(kind, settings, now)
        early, late = gate_mod.utc_firing_times(settings, kind, now)
        print(f"  next {kind:<7} {nxt:%a %d %b %H:%M} {nxt.tzname()}  "
              f"(cron fires {early} and {late} UTC; the wrong one exits 0)")

    # --- budget -----------------------------------------------------------
    guard = budget_mod.BudgetGuard(conn, settings, local.date().isoformat())
    st = guard.status()
    print(f"\nSpend {st.month}")
    print(f"  ${st.spent_aud:.2f} of ${st.cap_aud:.2f} AUD "
          f"({st.fraction_used * 100:.0f}%), ${st.remaining_aud:.2f} remaining")
    if warning := guard.warning():
        print(f"  ! {warning}")

    # --- private config ---------------------------------------------------
    print("\nPrivate config")
    if profile_is_real():
        source = "RADAR_PROFILE secret" if os.environ.get("RADAR_PROFILE") \
            else "config/profile.local.md"
        print(f"  profile          loaded from {source}")
    else:
        print("  profile          ! using the redacted example — fit scores would be "
              "meaningless. Create config/profile.local.md or set RADAR_PROFILE.")
    try:
        recipient = load_recipient()
        masked = recipient.split("@")[0][:2] + "***@" + recipient.split("@")[-1]
        print(f"  recipient        {masked}")
    except ConfigError:
        print("  recipient        ! RADAR_RECIPIENT is not set — no email can be sent.")
    print(f"  ANTHROPIC_API_KEY {'set' if os.environ.get('ANTHROPIC_API_KEY') else '! not set'}")

    # --- data quality -----------------------------------------------------
    unconfirmed = [w for w in load_watchlist() if not w.confirmed]
    if unconfirmed:
        print(f"\nWatchlist needing confirmation ({len(unconfirmed)} of "
              f"{len(load_watchlist())})")
        for entry in unconfirmed:
            print(f"  {entry.symbol:<6} {entry.name}")

    gaps = seed_baseline.unverified_baseline_claims(conn)
    if gaps:
        print(f"\nBaseline claims still unsourced: {len(gaps)} "
              f"(run `baseline-gaps` to list; the first deep scan must verify them)")

    last = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 5").fetchall()
    if last:
        print("\nRecent runs")
        for row in last:
            print(f"  #{row['id']:<4} {row['kind']:<7} {row['sydney_date']}  "
                  f"{row['status']:<13} {row['notes'] or ''}"[:110])
    conn.close()
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    settings = load_settings()
    conn = connect(settings.db_path)
    counts = seed_baseline.seed(conn, settings, force=args.force)
    conn.close()
    if not any(counts.values()):
        print(f"Baseline for {settings.baseline_date} already present; nothing inserted. "
              f"Use --force to rewrite it.")
    else:
        print(f"Seeded baseline {settings.baseline_date}: " +
              ", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


def cmd_prices(args: argparse.Namespace) -> int:
    """Live price fetch: macro, watchlist, and any alerts that would fire.

    Costs nothing — no Claude API call is involved. Prints only; pass ``--store``
    to write the readings into history the way the daily job will.
    """
    from .alerts import rules
    from .sources import macro as macro_mod
    from .sources import quotes as quotes_mod

    settings = load_settings()
    local = gate_mod.sydney_now(settings, _parse_now(args.now))
    sydney_date = local.date().isoformat()
    conn = connect(settings.db_path)
    run = start_run(conn, "manual", sydney_date)

    try:
        macro_readings, macro_failures = macro_mod.fetch_macro(run)
        changes = macro_mod.changes_since_last_snapshot(conn, sydney_date, macro_readings)

        print(f"Macro — {sydney_date} Sydney\n")
        print(f"  {'Metric':<26} {'Level':>12}  {'Day':>8}  {'Since last':>11}")
        by_key = {r.metric.key: r for r in macro_readings}
        for change in changes:
            reading = by_key[change.metric]
            day = reading.quote.pct_change
            day_text = f"{day:+.1f}%" if day is not None else "n/a"
            label = change.label + (" *" if change.is_proxy else "")
            print(f"  {label:<26} {change.latest:>12,.4g}  {day_text:>8}  "
                  f"{change.format_change():>11}")
        if any(c.is_proxy for c in changes):
            print("\n  * proxy series, not the underlying price — see the note in history")

        rate = macro_mod.usd_to_aud_from(macro_readings)
        if rate:
            print(f"\n  USD->AUD for costing: {rate:.4f} "
                  f"(config default {settings.budget.usd_to_aud:.4f})")

        entries = load_watchlist()
        readings, skipped, quote_failures = quotes_mod.fetch_watchlist(run, entries)
        print(f"\nWatchlist — {len(readings)} quoted, {len(skipped)} skipped\n")
        print(f"  {'Sym':<6} {'Close':>10} {'Cur':<4} {'Day':>8}  {'Date':<11} Exchange")
        for reading in sorted(readings, key=lambda r: r.entry.symbol):
            quote, pct = reading.quote, reading.pct_change
            print(f"  {reading.entry.symbol:<6} {quote.close:>10,.2f} {quote.currency:<4} "
                  f"{f'{pct:+.1f}%' if pct is not None else 'n/a':>8}  "
                  f"{quote.as_of_date:<11} {quote.exchange}")
        for skip in skipped:
            print(f"  {skip.symbol:<6} {'—':>10}      {'':>8}  not quoted: {skip.reason}")

        alerts = rules.evaluate(readings, macro_readings, settings.alerts, sydney_date)
        print(f"\nAlerts: {len(alerts)} would fire "
              f"(thresholds {settings.alerts.watchlist_move_pct:.0f}% stocks, "
              f"{settings.alerts.commodity_move_pct:.0f}% commodities/FX)")
        for alert in alerts:
            print(f"  [{alert.severity}] {alert.headline}")
        if not alerts:
            print("  Nothing breached a threshold — the daily job would send no email.")

        for failure in macro_failures + quote_failures:
            print(f"  ! fetch failed: {failure}")

        if args.store:
            macro_mod.store_macro(conn, run.id, sydney_date, macro_readings)
            quotes_mod.store_quotes(conn, run.id, readings)
            fresh = rules.store_new_alerts(conn, run.id, alerts)
            print(f"\nStored: {len(macro_readings)} macro, {len(readings)} quotes, "
                  f"{len(fresh)} new alerts")
        else:
            print("\n(nothing stored — pass --store to write these into history)")

        run.finish("partial" if (macro_failures or quote_failures) else "ok")
    except Exception as exc:  # noqa: BLE001 — recorded, then re-raised
        run.log_error("price fetch failed", exc)
        run.finish("failed", notes=f"{type(exc).__name__}: {exc}"[:500])
        raise
    finally:
        conn.close()
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    """Rebuild the history database from empty, then re-seed.

    ``seed --force`` rewrites baseline rows but leaves earlier ``runs`` and
    ``run_events`` in place, and those can hold text from a superseded config.
    Because the database is committed to a public repo, there needs to be a way
    to start genuinely clean. This also VACUUMs, so deleted text does not linger
    in free pages of the committed binary.
    """
    settings = load_settings()
    if not args.yes:
        print(f"This deletes {settings.db_path} and all run history in it.\n"
              f"Re-run with --yes to confirm.")
        return 1
    if settings.db_path.exists():
        settings.db_path.unlink()
    conn = connect(settings.db_path)
    counts = seed_baseline.seed(conn, settings)
    conn.execute("VACUUM")
    conn.close()
    print(f"History rebuilt at {settings.db_path}; baseline re-seeded: " +
          ", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    settings = load_settings()
    force = args.force or os.environ.get("RADAR_FORCE", "").lower() in ("1", "true", "yes")
    decision = gate_mod.evaluate(args.kind, settings, _parse_now(args.now), force=force)
    verdict = "RUN" if decision.should_run else "SKIP"
    print(f"{verdict}: {decision.reason}")
    # Exit 0 either way: a skipped cron firing is a success, not a failure.
    return 0


def cmd_baseline_gaps(args: argparse.Namespace) -> int:
    settings = load_settings()
    conn = connect(settings.db_path)
    gaps = seed_baseline.unverified_baseline_claims(conn)
    if not gaps:
        print("No unsourced baseline claims: every one has a real source.")
    else:
        print(f"{len(gaps)} baseline claims rest on the brief alone "
              f"(strength: weak). The first deep scan must verify each:\n")
        current = None
        for row in gaps:
            if row["slug"] != current:
                current = row["slug"]
                print(f"  {row['title']}")
            print(f"    - {row['claim']}: {row['number_value'] or '(no figure)'}")
    conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="radar", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--now", help="Override 'now' as a UTC ISO-8601 instant, for testing")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="show history, schedule, spend and config state")
    p_status.set_defaults(func=cmd_status)

    p_seed = sub.add_parser("seed", help="write the baseline snapshot")
    p_seed.add_argument("--force", action="store_true",
                        help="clear and rewrite an existing baseline")
    p_seed.set_defaults(func=cmd_seed)

    p_prices = sub.add_parser("prices", help="live macro + watchlist fetch (free, no API)")
    p_prices.add_argument("--store", action="store_true",
                          help="write the readings into history")
    p_prices.set_defaults(func=cmd_prices)

    p_reset = sub.add_parser("reset", help="delete all history and re-seed from empty")
    p_reset.add_argument("--yes", action="store_true", help="confirm the deletion")
    p_reset.set_defaults(func=cmd_reset)

    p_gate = sub.add_parser("gate", help="report whether a run should fire now")
    p_gate.add_argument("kind", choices=["weekly", "daily"])
    p_gate.add_argument("--force", action="store_true", help="bypass the schedule check")
    p_gate.set_defaults(func=cmd_gate)

    p_gaps = sub.add_parser("baseline-gaps", help="list baseline claims lacking a real source")
    p_gaps.set_defaults(func=cmd_baseline_gaps)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
