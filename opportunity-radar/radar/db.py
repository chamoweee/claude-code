"""SQLite access.

The database is committed to the repo, so every write must be deterministic and
every schema change must be idempotent — a run that re-applies the schema on an
existing file is normal, not an error.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import PACKAGE_ROOT

SCHEMA_PATH = PACKAGE_ROOT / "schema.sql"
SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: Path, *, create: bool = True) -> sqlite3.Connection:
    """Open the history database, applying the schema if needed."""
    db_path = Path(db_path)
    if not db_path.exists() and not create:
        raise FileNotFoundError(f"No history database at {db_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL would leave -wal/-shm files next to a committed database; plain
    # journalling keeps the working tree clean between runs.
    conn.execute("PRAGMA journal_mode = DELETE")
    if create:
        apply_schema(conn)
    return conn


def apply_schema(conn: sqlite3.Connection) -> int:
    """Apply schema.sql (idempotent) and record the version. Returns the version."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = row["v"] if row and row["v"] is not None else 0
    if current < SCHEMA_VERSION:
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, utc_now_iso()),
        )
        conn.commit()
    return SCHEMA_VERSION


@contextmanager
def session(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Connection context manager that commits on success, rolls back on error."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Row counts for every table, for the ``status`` command."""
    names = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {name: conn.execute(f"SELECT COUNT(*) AS n FROM {name}").fetchone()["n"]
            for name in names}
