"""Shared job scaffolding: the gate, the error path, the exit codes.

Both scheduled jobs have the same skeleton — decide whether this firing is the
real one, do the work, and make sure a failure is never silent. That skeleton
lives here so the two jobs differ only in what they actually do.

Exit codes are chosen so GitHub Actions tells the truth at a glance:

* ``0`` — ran, or correctly skipped because this was the wrong UTC firing, or
  halted on budget. All expected outcomes.
* ``1`` — something broke. The run is red in Actions *and* a notice email was
  attempted, so a failure reaches the inbox even if nobody looks at GitHub.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime

from .. import gate as gate_mod
from ..budget import BudgetExhausted, BudgetGuard
from ..config import ConfigError, Settings, load_recipient, load_settings
from ..db import connect
from ..report import render
from ..runlog import Run, start_run

EXIT_OK = 0
EXIT_FAILED = 1


@dataclass
class JobContext:
    settings: Settings
    conn: sqlite3.Connection
    run: Run
    guard: BudgetGuard
    sydney_date: str
    dry_run: bool


def force_requested(explicit: bool = False) -> bool:
    return explicit or os.environ.get("RADAR_FORCE", "").lower() in ("1", "true", "yes")


def open_job(kind: str, *, now: datetime | None = None, force: bool = False,
             dry_run: bool = False) -> JobContext | None:
    """Run the gate. Returns ``None`` when this firing should do nothing."""
    settings = load_settings()
    decision = gate_mod.evaluate(kind, settings, now, force=force_requested(force))
    if not decision.should_run:
        print(f"skip: {decision.reason}")
        return None

    print(f"run: {decision.reason}")
    conn = connect(settings.db_path)
    run = start_run(conn, kind, decision.sydney_date)
    return JobContext(
        settings=settings, conn=conn, run=run,
        guard=BudgetGuard(conn, settings, decision.sydney_date, run_id=run.id),
        sydney_date=decision.sydney_date, dry_run=dry_run,
    )


def send(subject: str, html: str, text: str, ctx: JobContext,
         sender=None) -> bool:
    """Send one email. Returns whether it went. Never raises into the caller."""
    if ctx.dry_run:
        print(f"[dry run] would send: {subject}")
        ctx.run.log("email_skipped", {"subject": subject, "reason": "dry run"})
        return False
    from ..mail import gmail

    # `is None`, not `or`: a perfectly good sender can be falsy (a callable
    # object with __len__, a Mock configured to be empty), and falling back to
    # the real Gmail sender because of that would send a live email from a test.
    if sender is None:
        sender = gmail.send_email
    try:
        recipient = load_recipient()
        message_id = sender(recipient=recipient, subject=subject, html=html, text=text)
    except (ConfigError, gmail.MailError) as exc:
        ctx.run.log_error(f"email failed: {subject}", exc)
        print(f"email failed: {exc}", file=sys.stderr)
        return False
    ctx.run.log("email_sent", {"subject": subject, "message_id": message_id})
    print(f"sent: {subject}")
    return True


def notify_failure(kind: str, sydney_date: str, errors: list[str],
                   ctx: JobContext | None = None, sender=None) -> None:
    """Best effort failure notice.

    This is the one place that must not throw, whatever state the run is in —
    the whole point is that a broken run still reaches the inbox. If even this
    fails, the traceback goes to the Actions log and the exit code stays 1.
    """
    if ctx is not None and ctx.dry_run:
        print(f"[dry run] would send failure notice: {errors}")
        return
    try:
        from ..mail import gmail

        if sender is None:
            sender = gmail.send_email
        run_id = ctx.run.id if ctx else None
        sender(
            recipient=load_recipient(),
            subject=f"Radar {kind} run failed — {sydney_date}",
            html=render.render_error_html(kind, sydney_date, errors, run_id),
            text=render.render_error_text(kind, sydney_date, errors, run_id),
        )
        print("failure notice sent")
    except Exception:  # noqa: BLE001 - last resort; the log is all that is left
        print("could not send the failure notice:", file=sys.stderr)
        traceback.print_exc()


def handle_budget_exhausted(exc: BudgetExhausted, kind: str, ctx: JobContext,
                            sender=None) -> int:
    """Halt cleanly and say so once, rather than failing silently every run.

    Halting is an expected outcome of a rule working, not a fault, so the run
    exits 0 and Actions stays green. The notice is sent once per month: a daily
    job that has hit the cap would otherwise send the same email every weekday
    until the 1st.
    """
    ctx.run.log("budget_halted", {"spent_aud": exc.spent_aud, "month": exc.month},
                level="warn")
    ctx.run.finish("budget_halted", notes=str(exc))
    print(str(exc), file=sys.stderr)

    already = ctx.conn.execute(
        "SELECT 1 FROM reports WHERE kind = 'budget' AND sydney_date LIKE ? LIMIT 1",
        (f"{exc.month}-%",)).fetchone()
    if already:
        print("budget notice already sent this month; staying quiet")
        return EXIT_OK

    sent = send(
        f"Radar halted — ${exc.spent_aud:.2f} of ${exc.cap_aud:.2f} AUD used",
        render.render_error_html(
            f"{kind} (budget)", ctx.sydney_date,
            [str(exc), "Runs resume automatically on the 1st. Nothing is broken — "
                       "this is the monthly cap doing its job."], ctx.run.id),
        render.render_error_text(f"{kind} (budget)", ctx.sydney_date, [str(exc)],
                                 ctx.run.id),
        ctx, sender=sender)
    if sent:
        ctx.conn.execute(
            "INSERT INTO reports (run_id, kind, sydney_date, subject, sent_at) "
            "VALUES (?, 'budget', ?, ?, datetime('now')) "
            "ON CONFLICT (kind, sydney_date) DO NOTHING",
            (ctx.run.id, ctx.sydney_date, "budget halt"))
        ctx.conn.commit()
    return EXIT_OK


def record_report(ctx: JobContext, kind: str, subject: str, path: str | None,
                  sent: bool) -> None:
    ctx.conn.execute(
        "INSERT INTO reports (run_id, kind, sydney_date, subject, path, sent_at) "
        "VALUES (?, ?, ?, ?, ?, CASE WHEN ? THEN datetime('now') ELSE NULL END) "
        "ON CONFLICT (kind, sydney_date) DO UPDATE SET subject = excluded.subject, "
        "path = excluded.path, sent_at = excluded.sent_at",
        (ctx.run.id, kind, ctx.sydney_date, subject, path, sent))
    ctx.conn.commit()


def write_report_file(ctx: JobContext, name: str, html: str, text: str) -> str:
    """Keep a copy on disk. Git-ignored — it is for debugging a bad email."""
    from ..config import REPORTS_DIR

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    html_path = REPORTS_DIR / f"{name}.html"
    html_path.write_text(html, encoding="utf-8")
    (REPORTS_DIR / f"{name}.txt").write_text(text, encoding="utf-8")
    return str(html_path)
