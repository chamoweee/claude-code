"""Run bookkeeping.

Every execution opens a ``runs`` row before it does anything else and closes it
in a ``finally``, so a crashed run is still visible as ``failed`` with its error
recorded rather than vanishing.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import traceback
from dataclasses import dataclass
from typing import Any, Iterator

from .db import utc_now_iso


def git_sha() -> str | None:
    """Best-effort commit SHA, for tracing a report back to the code that made it."""
    for env_var in ("GITHUB_SHA", "RADAR_GIT_SHA"):
        if os.environ.get(env_var):
            return os.environ[env_var][:40]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


@dataclass
class Run:
    """An open run. Use :func:`start_run` rather than constructing directly."""

    conn: sqlite3.Connection
    id: int
    kind: str
    sydney_date: str
    _status: str = "running"

    # -- logging ------------------------------------------------------------

    def log(self, event: str, detail: Any = None, level: str = "info") -> None:
        if detail is not None and not isinstance(detail, str):
            detail = json.dumps(detail, default=str, sort_keys=True)
        self.conn.execute(
            "INSERT INTO run_events (run_id, at, level, event, detail) VALUES (?, ?, ?, ?, ?)",
            (self.id, utc_now_iso(), level, event, detail),
        )
        self.conn.commit()

    def log_query(self, query: str, purpose: str = "") -> None:
        self.log("query", {"query": query, "purpose": purpose})

    def log_source(self, url: str, name: str = "", strength: str = "") -> None:
        self.log("source", {"url": url, "name": name, "strength": strength})

    def log_error(self, message: str, exc: BaseException | None = None) -> None:
        detail: dict[str, Any] = {"message": message}
        if exc is not None:
            detail["type"] = type(exc).__name__
            detail["traceback"] = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )[-4000:]
        self.log("error", detail, level="error")

    # -- lifecycle ----------------------------------------------------------

    def finish(self, status: str, notes: str | None = None) -> None:
        self._status = status
        self.conn.execute(
            "UPDATE runs SET status = ?, finished_at = ?, notes = ? WHERE id = ?",
            (status, utc_now_iso(), notes, self.id),
        )
        self.conn.commit()

    # -- reading back -------------------------------------------------------

    def events(self, level: str | None = None) -> list[sqlite3.Row]:
        if level:
            return list(self.conn.execute(
                "SELECT * FROM run_events WHERE run_id = ? AND level = ? ORDER BY id",
                (self.id, level)))
        return list(self.conn.execute(
            "SELECT * FROM run_events WHERE run_id = ? ORDER BY id", (self.id,)))

    def errors(self) -> list[sqlite3.Row]:
        return self.events(level="error")

    def sources(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT detail FROM run_events WHERE run_id = ? AND event = 'source' ORDER BY id",
            (self.id,),
        )
        seen: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                item = json.loads(row["detail"])
            except (TypeError, ValueError):
                continue
            seen.setdefault(item.get("url", ""), item)
        return list(seen.values())


def start_run(conn: sqlite3.Connection, kind: str, sydney_date: str) -> Run:
    cur = conn.execute(
        "INSERT INTO runs (kind, status, started_at, sydney_date, git_sha) "
        "VALUES (?, 'running', ?, ?, ?)",
        (kind, utc_now_iso(), sydney_date, git_sha()),
    )
    conn.commit()
    return Run(conn=conn, id=int(cur.lastrowid), kind=kind, sydney_date=sydney_date)


def run_scope(conn: sqlite3.Connection, kind: str, sydney_date: str) -> Iterator[Run]:
    """Context manager: marks the run ``failed`` and records the traceback if the
    body raises, then re-raises so the caller can send the error email."""
    from contextlib import contextmanager

    @contextmanager
    def _scope() -> Iterator[Run]:
        run = start_run(conn, kind, sydney_date)
        try:
            yield run
        except BaseException as exc:  # noqa: BLE001 — recorded, then re-raised
            run.log_error(f"{kind} run aborted", exc)
            run.finish("failed", notes=f"{type(exc).__name__}: {exc}"[:500])
            raise
        else:
            if run._status == "running":
                run.finish("ok")

    return _scope()


def last_run(conn: sqlite3.Connection, kind: str | None = None) -> sqlite3.Row | None:
    if kind:
        return conn.execute(
            "SELECT * FROM runs WHERE kind = ? ORDER BY id DESC LIMIT 1", (kind,)
        ).fetchone()
    return conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
