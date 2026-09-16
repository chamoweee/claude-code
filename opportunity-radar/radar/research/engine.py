"""Orchestration: build context, run the passes, validate, persist.

The weekly scan is three calls, not one. Splitting them keeps each prompt
focused, keeps a failure in one pass from losing the others, and lets the
budget guard stop between passes rather than mid-thought:

1. **Themes** — update every tracked theme, and verify the baseline claims that
   arrived without sources.
2. **Discovery** — look for new trends anywhere, against the 90-day evidence bar.
3. **Synthesis** — the three-line summary and the three actions, written with
   the first two passes' results in hand rather than guessed at up front.

The daily check is one small call, and usually returns nothing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..budget import BudgetExhausted
from ..config import Settings, load_profile
from ..db import utc_now_iso
from ..runlog import Run
from ..seed_baseline import BASELINE_SOURCE_URL
from . import scoring, validate
from .client import ResearchClient, ResearchError, load_prompt, render
from .schemas import Opportunity, ResearchResult, ThemeUpdate


@dataclass
class WeeklyResearch:
    result: ResearchResult = field(default_factory=ResearchResult)
    scored: list = field(default_factory=list)
    actionable: list = field(default_factory=list)
    other: list = field(default_factory=list)
    cost_aud: float = 0.0
    searches: int = 0
    failures: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Context blocks
# ---------------------------------------------------------------------------


def themes_block(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT slug, title, description, watch_for, status FROM themes "
        "WHERE active = 1 ORDER BY id").fetchall()
    parts = []
    for row in rows:
        parts.append(
            f"- **{row['slug']}** — {row['title']} (currently {row['status']})\n"
            f"  {row['description']}\n"
            f"  Watch for: {row['watch_for']}")
    return "\n".join(parts) or "(no themes tracked yet)"


def verify_block(conn: sqlite3.Connection) -> str:
    """The baseline claims that still rest on the brief rather than a source."""
    rows = conn.execute(
        "SELECT t.slug, e.claim, e.number_value FROM evidence e "
        "JOIN themes t ON t.id = e.subject_id "
        "WHERE e.subject_type = 'theme' AND e.source_url = ? ORDER BY t.slug",
        (BASELINE_SOURCE_URL,)).fetchall()
    if not rows:
        return "(none outstanding — every baseline claim now has a real source)"
    return "\n".join(
        f"- {row['slug']}: \"{row['claim']}\" stated as {row['number_value'] or 'no figure'}"
        for row in rows)


def macro_block(conn: sqlite3.Connection, as_of_date: str) -> str:
    rows = conn.execute(
        "SELECT metric, value, unit, value_text, note, as_of_date FROM macro_snapshots "
        "WHERE as_of_date <= ? ORDER BY as_of_date DESC, metric", (as_of_date,)).fetchall()
    seen, parts = set(), []
    for row in rows:
        if row["metric"] in seen:
            continue
        seen.add(row["metric"])
        value = row["value_text"] or (f"{row['value']:,.4g} {row['unit'] or ''}".strip()
                                      if row["value"] is not None else "no reading")
        line = f"- {row['metric']}: {value} (as at {row['as_of_date']})"
        if row["note"]:
            line += f" — {row['note']}"
        parts.append(line)
    return "\n".join(parts) or "(no macro readings yet)"


def existing_block(conn: sqlite3.Connection) -> str:
    themes = [r["slug"] for r in conn.execute("SELECT slug FROM themes WHERE active = 1")]
    opps = [r["title"] for r in conn.execute(
        "SELECT title FROM opportunities ORDER BY last_seen_date DESC LIMIT 40")]
    parts = ["Tracked themes: " + (", ".join(themes) or "none")]
    if opps:
        parts.append("Opportunities already reported: " + "; ".join(opps))
    return "\n".join(parts)


def watchlist_block(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT symbol, as_of_date, close, pct_change, currency FROM watchlist_quotes "
        "WHERE as_of_date >= date('now', '-10 days') ORDER BY symbol, as_of_date DESC"
    ).fetchall()
    seen, parts = set(), []
    for row in rows:
        if row["symbol"] in seen:
            continue
        seen.add(row["symbol"])
        change = f"{row['pct_change']:+.1f}%" if row["pct_change"] is not None else "n/a"
        parts.append(f"- {row['symbol']}: {row['close']:,.2f} {row['currency']} "
                     f"({change} on the day, as at {row['as_of_date']})")
    return "\n".join(parts) or "(no recent quotes)"


def opportunities_block(scored: list[tuple[Opportunity, scoring.ScoreResult]]) -> str:
    if not scored:
        return "(nothing cleared the evidence bar this week)"
    parts = []
    for opportunity, result in scored:
        line = (f"- **{opportunity.title}** (`{opportunity.slug}`) — "
                f"score {result.total:.1f}/10, personal fit "
                f"{opportunity.scores.personal_fit}/10. {opportunity.summary}")
        if result.was_capped:
            line += f" [{result.capped_reason}]"
        if not opportunity.has_individual_evidence:
            line += " [no evidence individuals actually earn]"
        parts.append(line)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# The passes
# ---------------------------------------------------------------------------


def system_prompt(settings: Settings, today: str) -> str:
    return render(load_prompt("system"), today=today, profile=load_profile().strip())


def run_theme_pass(conn, settings, client: ResearchClient, today: str,
                   rejected: list[str]) -> tuple[list[ThemeUpdate], Any]:
    known = [r["slug"] for r in conn.execute("SELECT slug FROM themes WHERE active = 1")]
    user = render(load_prompt("theme_update"),
                  themes_block=themes_block(conn),
                  macro_block=macro_block(conn, today),
                  verify_block=verify_block(conn))
    answer = client.ask(system=system_prompt(settings, today), user=user,
                        purpose="theme_update",
                        max_searches=settings.research.max_searches_themes,
                        effort=settings.research.weekly_effort)
    updates = validate.validate_theme_updates(
        answer.payload, known, today=date.fromisoformat(today), rejected=rejected)
    return updates, answer


def run_discovery_pass(conn, settings, client: ResearchClient, today: str,
                       rejected: list[str]) -> tuple[list[Opportunity], Any]:
    research = settings.research
    user = render(load_prompt("discovery"),
                  max_new_trends=research.max_new_trends,
                  max_age_days=research.evidence_max_age_days,
                  existing_block=existing_block(conn))
    answer = client.ask(system=system_prompt(settings, today), user=user,
                        purpose="discovery",
                        max_searches=research.max_searches_discovery,
                        effort=research.weekly_effort)
    known_themes = [r["slug"] for r in conn.execute("SELECT slug FROM themes")]
    opportunities = validate.validate_opportunities(
        answer.payload, today=date.fromisoformat(today),
        max_age_days=research.evidence_max_age_days,
        max_items=research.max_new_trends, rejected=rejected,
        known_theme_slugs=known_themes)
    return opportunities, answer


def run_synthesis_pass(conn, settings, client: ResearchClient, today: str,
                       scored: list, rejected: list[str]) -> tuple[list, list[str], Any]:
    user = render(load_prompt("synthesis"),
                  macro_block=macro_block(conn, today),
                  themes_block=themes_block(conn),
                  opportunities_block=opportunities_block(scored),
                  watchlist_block=watchlist_block(conn))
    answer = client.ask(system=system_prompt(settings, today), user=user,
                        purpose="synthesis", max_searches=0,
                        effort=settings.research.weekly_effort, max_tokens=8_000)
    actions = validate.validate_actions(
        answer.payload, max_minutes=settings.research.max_action_minutes,
        rejected=rejected)
    return actions, validate.validate_summary(answer.payload), answer


def run_weekly(conn: sqlite3.Connection, settings: Settings, run: Run,
               client: ResearchClient, today: str) -> WeeklyResearch:
    """All three passes. A failure in one is recorded and the rest continue."""
    out = WeeklyResearch()
    rejected = out.result.rejected

    def attempt(name, fn):
        try:
            return fn()
        except BudgetExhausted:
            raise
        except (ResearchError, Exception) as exc:  # noqa: BLE001 — logged, then carried
            out.failures.append(f"{name}: {exc}")
            run.log_error(f"{name} pass failed", exc)
            return None

    themed = attempt("theme_update",
                     lambda: run_theme_pass(conn, settings, client, today, rejected))
    if themed:
        out.result.theme_updates, answer = themed
        out.cost_aud += answer.cost_aud
        out.searches += answer.searches

    discovered = attempt("discovery",
                         lambda: run_discovery_pass(conn, settings, client, today, rejected))
    if discovered:
        out.result.opportunities, answer = discovered
        out.cost_aud += answer.cost_aud
        out.searches += answer.searches

    research = settings.research
    out.scored = scoring.rank(out.result.opportunities, research,
                              research.no_individual_evidence_cap)
    out.actionable, out.other = scoring.split_by_fit(out.scored,
                                                     research.personal_fit_threshold)

    synthesised = attempt("synthesis", lambda: run_synthesis_pass(
        conn, settings, client, today, out.scored, rejected))
    if synthesised:
        out.result.actions, out.result.summary, answer = synthesised
        out.cost_aud += answer.cost_aud
        out.searches += answer.searches

    run.log("weekly_research", {
        "themes": len(out.result.theme_updates),
        "opportunities": len(out.result.opportunities),
        "actions": len(out.result.actions),
        "rejected": len(rejected),
        "searches": out.searches,
        "cost_aud": round(out.cost_aud, 4),
        "failures": out.failures,
    })
    for reason in rejected:
        run.log("rejected", reason, level="warn")
    return out


def run_daily(conn: sqlite3.Connection, settings: Settings, run: Run,
              client: ResearchClient, today: str) -> tuple[list, list[str]]:
    """The weekday news check. Returns alerts and a list of rejection reasons."""
    rejected: list[str] = []
    user = render(load_prompt("daily_news"), today=today,
                  themes_block=themes_block(conn))
    answer = client.ask(system=system_prompt(settings, today), user=user,
                        purpose="daily_news",
                        max_searches=settings.research.max_searches_daily,
                        effort=settings.research.daily_effort, max_tokens=4_000)
    alerts = validate.validate_news_alerts(
        answer.payload, today=date.fromisoformat(today), rejected=rejected)
    run.log("daily_research", {"alerts": len(alerts), "rejected": len(rejected),
                               "cost_aud": round(answer.cost_aud, 4)})
    return alerts, rejected


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def store_theme_updates(conn: sqlite3.Connection, run_id: int, as_of_date: str,
                        updates: list[ThemeUpdate]) -> int:
    stored = 0
    for update in updates:
        row = conn.execute("SELECT id, status FROM themes WHERE slug = ?",
                           (update.slug,)).fetchone()
        if not row:
            continue
        theme_id, prev_status = int(row["id"]), row["status"]
        conn.execute(
            "INSERT INTO theme_updates (theme_id, run_id, as_of_date, status, "
            "prev_status, reason) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (theme_id, as_of_date) DO UPDATE SET "
            "status = excluded.status, reason = excluded.reason, run_id = excluded.run_id",
            (theme_id, run_id, as_of_date, update.status, prev_status, update.reason))
        conn.execute("UPDATE themes SET status = ? WHERE id = ?", (update.status, theme_id))
        _store_evidence(conn, run_id, "theme", theme_id, update.evidence)
        stored += 1
    conn.commit()
    return stored


def store_opportunities(conn: sqlite3.Connection, run_id: int, as_of_date: str,
                        scored: list[tuple[Opportunity, scoring.ScoreResult]]) -> int:
    stored = 0
    for opportunity, result in scored:
        theme_id = None
        if opportunity.theme_slug:
            row = conn.execute("SELECT id FROM themes WHERE slug = ?",
                               (opportunity.theme_slug,)).fetchone()
            theme_id = int(row["id"]) if row else None

        conn.execute(
            "INSERT INTO opportunities (slug, theme_id, title, summary, who_earns, "
            "platform_revenue_evidence, individual_earnings_evidence, "
            "startup_cost_aud_min, startup_cost_aud_max, time_to_first_dollar_days, "
            "skills_required, saturation, red_flags, au_eligibility, "
            "first_seen_date, last_seen_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (slug) DO UPDATE SET last_seen_date = excluded.last_seen_date, "
            "summary = excluded.summary, "
            "individual_earnings_evidence = excluded.individual_earnings_evidence, "
            "saturation = excluded.saturation, red_flags = excluded.red_flags",
            (opportunity.slug, theme_id, opportunity.title, opportunity.summary,
             opportunity.who_earns, opportunity.platform_revenue_evidence,
             opportunity.individual_earnings_evidence, opportunity.startup_cost_aud_min,
             opportunity.startup_cost_aud_max, opportunity.time_to_first_dollar_days,
             opportunity.skills_required, opportunity.saturation, opportunity.red_flags,
             opportunity.au_eligibility, as_of_date, as_of_date))

        opportunity_id = int(conn.execute(
            "SELECT id FROM opportunities WHERE slug = ?",
            (opportunity.slug,)).fetchone()["id"])

        scores = opportunity.scores
        conn.execute(
            "INSERT INTO scores (opportunity_id, run_id, as_of_date, evidence_strength, "
            "personal_fit, capital_fit, hours_fit, speed_to_dollar, risk, total, "
            "capped_reason, rationale) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (opportunity_id, as_of_date) DO UPDATE SET "
            "total = excluded.total, capped_reason = excluded.capped_reason",
            (opportunity_id, run_id, as_of_date, scores.evidence_strength,
             scores.personal_fit, scores.capital_fit, scores.hours_fit,
             scores.speed_to_dollar, scores.risk, result.total, result.capped_reason,
             "; ".join(f"{k}: {v}" for k, v in scores.reasons.items())))

        _store_evidence(conn, run_id, "opportunity", opportunity_id, opportunity.evidence)
        stored += 1
    conn.commit()
    return stored


def store_actions(conn: sqlite3.Connection, run_id: int, as_of_date: str,
                  actions: list) -> int:
    for action in actions:
        opportunity_id = None
        if action.opportunity_slug:
            row = conn.execute("SELECT id FROM opportunities WHERE slug = ?",
                               (action.opportunity_slug,)).fetchone()
            opportunity_id = int(row["id"]) if row else None
        conn.execute(
            "INSERT INTO actions (run_id, as_of_date, rank, title, why, est_minutes, "
            "opportunity_id) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (as_of_date, rank) DO UPDATE SET title = excluded.title, "
            "why = excluded.why, est_minutes = excluded.est_minutes",
            (run_id, as_of_date, action.rank, action.title, action.why,
             action.est_minutes, opportunity_id))
    conn.commit()
    return len(actions)


def _store_evidence(conn: sqlite3.Connection, run_id: int, subject_type: str,
                    subject_id: int, evidence) -> None:
    for item in evidence:
        existing = conn.execute(
            "SELECT 1 FROM evidence WHERE subject_type = ? AND subject_id = ? "
            "AND source_url = ? AND claim = ? LIMIT 1",
            (subject_type, subject_id, item.source_url, item.claim)).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO evidence (run_id, subject_type, subject_id, claim, "
            "number_value, source_name, source_url, source_date, source_strength, "
            "captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, subject_type, subject_id, item.claim, item.number_value,
             item.source_name, item.source_url, item.source_date,
             item.source_strength, utc_now_iso()))


def retire_baseline_claims(conn: sqlite3.Connection, slug: str) -> int:
    """Drop a theme's unsourced baseline claims once real evidence has replaced them."""
    row = conn.execute("SELECT id FROM themes WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return 0
    theme_id = int(row["id"])
    real = conn.execute(
        "SELECT COUNT(*) AS n FROM evidence WHERE subject_type = 'theme' "
        "AND subject_id = ? AND source_url != ?",
        (theme_id, BASELINE_SOURCE_URL)).fetchone()["n"]
    if not real:
        return 0
    cur = conn.execute(
        "DELETE FROM evidence WHERE subject_type = 'theme' AND subject_id = ? "
        "AND source_url = ?", (theme_id, BASELINE_SOURCE_URL))
    conn.commit()
    return cur.rowcount
