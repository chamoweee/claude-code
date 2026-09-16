"""The weekday 07:00 Sydney light check.

Silent by design. On most days this job fetches prices, finds nothing over a
threshold, finds no rate decision or theme news, sends nothing, and exits 0.

Price rules run first and cost nothing. The research call — which does cost — is
skipped entirely when the budget is tight, because a threshold breach is the
part that genuinely cannot wait, and it needs no model at all.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from ..alerts import rules
from ..alerts.rules import Alert
from ..budget import BudgetExhausted
from ..config import load_watchlist
from ..report import render
from ..research.client import ResearchClient
from ..research.engine import run_daily as research_daily
from ..sources import macro as macro_mod
from ..sources import quotes as quotes_mod
from . import common
from .common import EXIT_FAILED, EXIT_OK, JobContext

KIND = "daily"


def price_alerts(ctx: JobContext) -> tuple[list[Alert], list[str]]:
    """The deterministic half: quotes in, thresholds applied, no model."""
    failures: list[str] = []

    readings, macro_failures = macro_mod.fetch_macro(ctx.run)
    failures += macro_failures
    if readings:
        macro_mod.store_macro(ctx.conn, ctx.run.id, ctx.sydney_date, readings)

    quotes, skipped, quote_failures = quotes_mod.fetch_watchlist(ctx.run, load_watchlist())
    failures += quote_failures
    if quotes:
        quotes_mod.store_quotes(ctx.conn, ctx.run.id, quotes)

    alerts = rules.evaluate(quotes, readings, ctx.settings.alerts, ctx.sydney_date)
    print(f"prices: {len(readings)} macro, {len(quotes)} quotes, "
          f"{len(alerts)} over threshold")
    return alerts, failures


def news_alerts(ctx: JobContext, client: ResearchClient | None) -> tuple[list[Alert], list[str]]:
    """The research half: rate decisions, CPI, rebate changes, theme news."""
    estimate = None
    client = client or ResearchClient(ctx.settings, ctx.guard, ctx.run)
    estimate = client.estimate_aud(ctx.settings.research.max_searches_daily, 4_000)
    try:
        ctx.guard.check(estimated_aud=estimate)
    except BudgetExhausted as exc:
        # Not fatal here. The price rules already ran and can still email.
        ctx.run.log("news_check_skipped", {"reason": str(exc)}, level="warn")
        print(f"news check skipped: {exc}", file=sys.stderr)
        return [], [f"news check skipped: {exc}"]

    found, rejected = research_daily(ctx.conn, ctx.settings, ctx.run, client,
                                     ctx.sydney_date)
    for reason in rejected:
        ctx.run.log("rejected", reason, level="warn")

    alerts = [Alert(rule=item.rule, subject=item.subject, headline=item.headline,
                    detail=item.detail, severity=item.severity,
                    source_url=item.source_url).with_context(ctx.sydney_date)
              for item in found]
    print(f"news: {len(alerts)} alerts, {len(rejected)} rejected")
    return alerts, []


def run(ctx: JobContext, client: ResearchClient | None = None, sender=None) -> int:
    alerts, failures = price_alerts(ctx)

    # A research failure must never cost us a threshold breach. The price rules
    # are the part that genuinely cannot wait, they cost nothing, and they have
    # already run by this point — so a broken news check degrades to
    # price-only alerts and a recorded failure, rather than losing the email.
    try:
        news, news_failures = news_alerts(ctx, client)
    except Exception as exc:  # noqa: BLE001 - recorded, reported, not fatal
        ctx.run.log_error("daily news check failed", exc)
        news, news_failures = [], [f"news check failed: {type(exc).__name__}: {exc}"]
        print(f"news check failed, continuing with price alerts: {exc}", file=sys.stderr)
    failures += news_failures

    # Dedupe against what has already been emailed, so one event buzzes once.
    fresh = rules.store_new_alerts(ctx.conn, ctx.run.id, alerts + news)

    for failure in failures:
        print(f"  ! {failure}", file=sys.stderr)

    if not fresh:
        print("nothing triggered — no email, as designed")
        ctx.run.finish("partial" if failures else "ok",
                       notes="no alerts" + (f"; {len(failures)} fetch failures"
                                            if failures else ""))
        return EXIT_OK

    html = render.render_alert_html(fresh, ctx.sydney_date)
    text = render.render_alert_text(fresh, ctx.sydney_date)
    subject = render.alert_subject(fresh, ctx.sydney_date)

    path = common.write_report_file(ctx, f"{ctx.sydney_date}-alert", html, text)
    sent = common.send(subject, html, text, ctx, sender=sender)
    if sent:
        rules.mark_emailed(ctx.conn, fresh)
    common.record_report(ctx, "daily_alert", subject, path, sent)

    ctx.run.finish("partial" if (failures or not sent) else "ok",
                   notes=f"{len(fresh)} alerts")
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
        ctx.run.log_error("daily run failed", exc)
        ctx.run.finish("failed", notes=f"{type(exc).__name__}: {exc}"[:500])
        print(f"daily run failed: {exc}", file=sys.stderr)
        common.notify_failure(KIND, ctx.sydney_date,
                              [f"{type(exc).__name__}: {exc}"], ctx)
        return EXIT_FAILED
    finally:
        ctx.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
