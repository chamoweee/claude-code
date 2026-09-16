"""Seed snapshot #1 — the state of the world as stated on 16 Sep 2026.

This writes the brief's own starting figures into history so that the first
weekly deep scan has something to compute week-on-week changes against.

Those figures arrived without source links, so they are recorded at strength
``weak`` against a ``baseline://brief`` sentinel URL. The first deep scan is
expected to replace each one with a primary source. Applying the source rules to
our own baseline is the point: nothing gets a free pass for being ours.

Seeding is idempotent. Re-running never overwrites a later correction.
"""

from __future__ import annotations

import sqlite3

from .config import Settings, load_theme_seeds
from .db import utc_now_iso
from .runlog import Run, start_run

BASELINE_SOURCE_URL = "baseline://brief"
BASELINE_SOURCE_NAME = "Chamk baseline brief, 16 Sep 2026"
BASELINE_STRENGTH = "weak"

# metric, value, unit, value_text, note
BASELINE_MACRO: tuple[tuple[str, float | None, str | None, str | None, str], ...] = (
    ("brent", 108.0, "USD/bbl", "~$108",
     "Elevated on the US-Iran conflict. Verify spot and the conflict framing."),
    ("gold", 4290.0, "USD/oz", "~$4,290",
     "Down from a ~$5,300 peak. Verify both the spot price and the peak date."),
    ("copper", None, "% y/y", "+38% y/y",
     "Year-on-year change only; no level given. Establish a level and the y/y window."),
    ("uranium", None, "USD/lb", None,
     "Tracked theme but no baseline figure supplied. First deep scan must establish one."),
    ("rba_cash_rate", 4.35, "%", "4.35%, further hikes forecast",
     "Verify against the RBA's own rate decision page — this is a primary-source number."),
    ("fed_decision", None, None, "Hike expected at the 16 Sep 2026 meeting",
     "An expectation, not an outcome. First run after the meeting must record what happened."),
    ("aud_usd", None, "USD", None,
     "No baseline supplied. Needed for the 3% FX alert and for USD->AUD cost conversion."),
    ("sydney_vacancy_rate", 2.2, "%", "2.2%",
     "Sydney-wide. Postcode-level vacancy is the figure that actually matters here."),
)


def seed(conn: sqlite3.Connection, settings: Settings, *, force: bool = False) -> dict[str, int]:
    """Write the baseline. Returns counts of what was actually inserted."""
    date = settings.baseline_date
    run = start_run(conn, "seed", date)
    counts = {"themes": 0, "macro": 0, "evidence": 0, "theme_updates": 0}
    try:
        if force:
            _clear_baseline(conn)
            run.log("seed", "existing baseline cleared before re-seed", level="warn")

        counts["macro"] = _seed_macro(conn, run, date)
        themes, updates, evidence = _seed_themes(conn, run, settings, date)
        counts["themes"], counts["theme_updates"], counts["evidence"] = themes, updates, evidence

        run.log("seed", counts)
        run.finish("ok", notes=f"baseline {date}: " + ", ".join(
            f"{k}={v}" for k, v in counts.items()))
    except Exception as exc:  # noqa: BLE001 — recorded, then re-raised
        run.log_error("baseline seed failed", exc)
        run.finish("failed", notes=f"{type(exc).__name__}: {exc}"[:500])
        raise
    return counts


def _clear_baseline(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM evidence WHERE source_url = ?", (BASELINE_SOURCE_URL,))
    conn.execute("DELETE FROM theme_updates WHERE theme_id IN "
                 "(SELECT id FROM themes WHERE is_baseline = 1)")
    conn.execute("DELETE FROM themes WHERE is_baseline = 1")
    conn.execute("DELETE FROM macro_snapshots WHERE source_url = ?", (BASELINE_SOURCE_URL,))
    conn.commit()


def _seed_macro(conn: sqlite3.Connection, run: Run, date: str) -> int:
    inserted = 0
    for metric, value, unit, value_text, note in BASELINE_MACRO:
        cur = conn.execute(
            "INSERT INTO macro_snapshots (run_id, as_of_date, metric, value, unit, "
            "value_text, source_name, source_url, source_date, source_strength, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (as_of_date, metric) DO NOTHING",
            (run.id, date, metric, value, unit, value_text, BASELINE_SOURCE_NAME,
             BASELINE_SOURCE_URL, date, BASELINE_STRENGTH, note),
        )
        inserted += cur.rowcount if cur.rowcount > 0 else 0
    conn.commit()
    run.log("seed_macro", {"inserted": inserted, "metrics": len(BASELINE_MACRO)})
    return inserted


def _seed_themes(conn: sqlite3.Connection, run: Run, settings: Settings,
                 date: str) -> tuple[int, int, int]:
    themes = updates = evidence = 0
    for seed_theme in load_theme_seeds():
        cur = conn.execute(
            "INSERT INTO themes (slug, title, description, watch_for, status, "
            "is_baseline, active, created_date) VALUES (?, ?, ?, ?, ?, 1, 1, ?) "
            "ON CONFLICT (slug) DO NOTHING",
            (seed_theme.slug, seed_theme.title, seed_theme.description.strip(),
             seed_theme.watch_for.strip(), seed_theme.status, date),
        )
        if cur.rowcount > 0:
            themes += 1

        row = conn.execute("SELECT id FROM themes WHERE slug = ?", (seed_theme.slug,)).fetchone()
        theme_id = int(row["id"])

        cur = conn.execute(
            "INSERT INTO theme_updates (theme_id, run_id, as_of_date, status, prev_status, "
            "reason) VALUES (?, ?, ?, ?, NULL, ?) "
            "ON CONFLICT (theme_id, as_of_date) DO NOTHING",
            (theme_id, run.id, date, seed_theme.status,
             "Baseline status as stated in the brief; not yet independently verified."),
        )
        if cur.rowcount > 0:
            updates += 1

        already = conn.execute(
            "SELECT 1 FROM evidence WHERE subject_type = 'theme' AND subject_id = ? "
            "AND source_url = ? LIMIT 1",
            (theme_id, BASELINE_SOURCE_URL),
        ).fetchone()
        if already:
            continue

        for item in seed_theme.evidence:
            conn.execute(
                "INSERT INTO evidence (run_id, subject_type, subject_id, claim, "
                "number_value, source_name, source_url, source_date, source_strength, "
                "captured_at) VALUES (?, 'theme', ?, ?, ?, ?, ?, ?, ?, ?)",
                (run.id, theme_id, item.get("claim", ""), item.get("number_value"),
                 BASELINE_SOURCE_NAME, BASELINE_SOURCE_URL, date, BASELINE_STRENGTH,
                 utc_now_iso()),
            )
            evidence += 1
            if item.get("note"):
                run.log("verify_needed",
                        {"theme": seed_theme.slug, "claim": item.get("claim"),
                         "note": item["note"]})
    conn.commit()
    run.log("seed_themes", {"themes": themes, "updates": updates, "evidence": evidence})
    return themes, updates, evidence


def unverified_baseline_claims(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Baseline claims still resting on the brief rather than a real source."""
    return list(conn.execute(
        "SELECT t.slug, t.title, e.claim, e.number_value FROM evidence e "
        "JOIN themes t ON t.id = e.subject_id "
        "WHERE e.subject_type = 'theme' AND e.source_url = ? ORDER BY t.slug, e.id",
        (BASELINE_SOURCE_URL,),
    ))
