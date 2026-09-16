"""The Monday 07:00 Sydney deep scan.

Order matters. Prices are fetched and stored first, so that if research fails
the report still carries real macro and watchlist numbers rather than nothing.
The email is the last thing that happens, and it is sent whether or not the week
was interesting: a missing Monday email must mean something broke.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from ..alerts import rules
from ..budget import BudgetExhausted
from ..config import load_watchlist
from ..report import build, render
from ..research import engine, scoring
from ..research.client import ResearchClient
from ..sources import macro as macro_mod
from ..sources import quotes as quotes_mod
from . import common
from .common import EXIT_FAILED, EXIT_OK, JobContext

KIND = "weekly"


def collect_prices(ctx: JobContext) -> list[str]:
    """Macro and watchlist, stored before anything expensive is attempted."""
    failures: list[str] = []

    readings, macro_failures = macro_mod.fetch_macro(ctx.run)
    failures += macro_failures
    if readings:
        macro_mod.store_macro(ctx.conn, ctx.run.id, ctx.sydney_date, readings)
        rate = macro_mod.record_fx_rate(ctx.conn, ctx.run, readings)
        if rate:
            print(f"USD->AUD {rate:.4f} (config default "
                  f"{ctx.settings.budget.usd_to_aud:.4f})")

    quotes, skipped, quote_failures = quotes_mod.fetch_watchlist(ctx.run, load_watchlist())
    failures += quote_failures
    if quotes:
        quotes_mod.store_quotes(ctx.conn, ctx.run.id, quotes)
    for skip in skipped:
        ctx.run.log("watchlist_skipped", {"symbol": skip.symbol, "reason": skip.reason})

    # Weekly price alerts are stored so the report can recap them, but the daily
    # job owns emailing them — a threshold breach should not arrive twice.
    alerts = rules.evaluate(quotes, readings, ctx.settings.alerts, ctx.sydney_date)
    rules.store_new_alerts(ctx.conn, ctx.run.id, alerts)

    print(f"prices: {len(readings)} macro, {len(quotes)} quotes, "
          f"{len(skipped)} skipped, {len(failures)} failed")
    return failures


def run(ctx: JobContext, client: ResearchClient | None = None,
        sender=None) -> int:
    price_failures = collect_prices(ctx)

    client = client or ResearchClient(ctx.settings, ctx.guard, ctx.run)
    weekly = engine.run_weekly(ctx.conn, ctx.settings, ctx.run, client, ctx.sydney_date)

    engine.store_theme_updates(ctx.conn, ctx.run.id, ctx.sydney_date,
                               weekly.result.theme_updates)
    engine.store_opportunities(ctx.conn, ctx.run.id, ctx.sydney_date, weekly.scored)
    engine.store_actions(ctx.conn, ctx.run.id, ctx.sydney_date, weekly.result.actions)

    # A baseline claim only retires once something properly sourced replaces it.
    retired = sum(engine.retire_baseline_claims(ctx.conn, update.slug)
                  for update in weekly.result.theme_updates)
    if retired:
        print(f"retired {retired} unsourced baseline claims, now properly sourced")

    weekly.failures = list(weekly.failures) + price_failures
    data = build.build_weekly(ctx.conn, ctx.settings, ctx.run, weekly,
                              ctx.sydney_date, ctx.guard)
    html = render.render_weekly_html(data, scoring.format_scoring_table)
    text = render.render_weekly_text(data)
    subject = render.weekly_subject(data)

    path = common.write_report_file(ctx, f"{ctx.sydney_date}-weekly", html, text)
    sent = common.send(subject, html, text, ctx, sender=sender)
    common.record_report(ctx, "weekly", subject, path, sent)

    print(f"weekly: {len(weekly.result.theme_updates)} themes, "
          f"{len(weekly.actionable)} leads, {len(weekly.other)} other, "
          f"{len(weekly.result.actions)} actions, {weekly.searches} searches, "
          f"${weekly.cost_aud:.2f} AUD")

    status = "partial" if (weekly.failures or not sent) else "ok"
    ctx.run.finish(status, notes=f"${weekly.cost_aud:.2f} AUD, "
                                 f"{weekly.searches} searches")
    return EXIT_OK if sent or ctx.dry_run else EXIT_FAILED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="ignore the schedule gate and run now")
    parser.add_argument("--dry-run", action="store_true",
                        help="do everything except send email")
    parser.add_argument("--now", help="override 'now' as a UTC ISO-8601 instant")
    args = parser.parse_args(argv)

    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
    ctx = common.open_job(KIND, now=now, force=args.force, dry_run=args.dry_run)
    if ctx is None:
        return EXIT_OK

    try:
        return run(ctx)
    except BudgetExhausted as exc:
        return common.handle_budget_exhausted(exc, KIND, ctx)
    except Exception as exc:  # noqa: BLE001 - recorded, emailed, then reported red
        ctx.run.log_error("weekly run failed", exc)
        ctx.run.finish("failed", notes=f"{type(exc).__name__}: {exc}"[:500])
        print(f"weekly run failed: {exc}", file=sys.stderr)
        common.notify_failure(KIND, ctx.sydney_date,
                              [f"{type(exc).__name__}: {exc}"], ctx)
        return EXIT_FAILED
    finally:
        ctx.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
