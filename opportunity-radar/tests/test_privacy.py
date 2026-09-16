"""This repository is public, so the privacy boundary is a testable invariant.

These caught a real leak during Stage 1: the rental theme named a suburb and a
specific property in a committed config file. Keep them passing.
"""

from __future__ import annotations

import re
import subprocess

import pytest

from radar.config import CONFIG_DIR, PACKAGE_ROOT, PROJECT_ROOT

# Things that identify a person or a household, as opposed to a market.
# Non-capturing groups throughout: findall must return the matched text, not a
# group, or an empty string gets reported as a hit.
PERSONAL_PATTERNS = re.compile(
    r"granny\s*flat"
    r"|\bchhay\b"
    r"|[\w.+-]+@[\w-]+\.[\w.]+"          # any email address
    r"|\b\d{1,4}\s+\w+\s+(?:street|st|road|rd|avenue|ave|crescent|cres)\b",
    re.IGNORECASE,
)

# Documentation placeholders. Real addresses never use these domains (RFC 2606).
PLACEHOLDER = re.compile(r"@(?:example\.(?:com|org|net)|\w*\.example)$", re.IGNORECASE)


def real_hits(text: str) -> list[str]:
    return [h for h in PERSONAL_PATTERNS.findall(text) if not PLACEHOLDER.search(h)]

COMMITTED_TEXT = (
    list(CONFIG_DIR.glob("*.toml"))
    + [CONFIG_DIR / "profile.example.md"]
    + list(PACKAGE_ROOT.rglob("*.py"))
    + [PACKAGE_ROOT / "schema.sql"]
    + [PROJECT_ROOT / "CLAUDE.md", PROJECT_ROOT / "README.md"]
)


@pytest.mark.parametrize("path", COMMITTED_TEXT, ids=lambda p: p.name)
def test_committed_files_carry_no_personal_identifiers(path):
    hits = real_hits(path.read_text(encoding="utf-8"))
    assert not hits, (
        f"{path.relative_to(PROJECT_ROOT)} contains personal detail {hits!r}. "
        f"It belongs in the private profile, not in a public repo."
    )


def test_the_real_profile_is_git_ignored():
    """A missing ignore rule here would publish the whole profile."""
    result = subprocess.run(
        ["git", "check-ignore", "config/profile.local.md"],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, "config/profile.local.md is NOT git-ignored"


def test_rendered_reports_are_git_ignored():
    result = subprocess.run(
        ["git", "check-ignore", "data/reports/weekly.html"],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, "rendered reports are NOT git-ignored"


def test_the_committed_database_is_non_identifying():
    """Scans the raw file, not just live rows: deleted text lingers in free pages."""
    db_path = PROJECT_ROOT / "data" / "radar.db"
    if not db_path.exists():
        pytest.skip("no committed database yet")
    hits = real_hits(db_path.read_bytes().decode("latin-1"))
    assert not hits, (
        f"data/radar.db contains personal detail {hits!r}. "
        f"Run `python -m radar.cli reset --yes`, which rebuilds and VACUUMs."
    )


def test_no_committed_default_recipient(monkeypatch):
    """The recipient must come from a secret; there is no fallback to fall back to."""
    from radar.config import ConfigError, load_recipient

    monkeypatch.delenv("RADAR_RECIPIENT", raising=False)
    with pytest.raises(ConfigError, match="RADAR_RECIPIENT"):
        load_recipient()
