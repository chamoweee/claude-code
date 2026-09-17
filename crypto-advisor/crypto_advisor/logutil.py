"""Shared append-only CSV loggers for excluded coins and data-quality issues.

Every "missing/suspicious field" and "coin excluded" event in the pipeline goes
through here instead of being silently defaulted -- see README "Data quality".
"""
from __future__ import annotations

import csv
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data"
EXCLUDED_LOG = DATA_DIR / "excluded_coins_log.csv"
QUALITY_LOG = DATA_DIR / "data_quality_log.csv"

_EXCLUDED_HEADER = ["timestamp", "coin_id", "symbol", "reason", "value", "threshold"]
_QUALITY_HEADER = ["timestamp", "coin_id", "source", "field", "issue"]


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def _append_row(path: Path, header: list[str], row: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def log_excluded(coin_id: str, symbol: str, reason: str, value=None, threshold=None) -> None:
    _append_row(
        EXCLUDED_LOG,
        _EXCLUDED_HEADER,
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "coin_id": coin_id,
            "symbol": symbol,
            "reason": reason,
            "value": value,
            "threshold": threshold,
        },
    )


def log_data_quality(coin_id: str, source: str, field: str, issue: str) -> None:
    _append_row(
        QUALITY_LOG,
        _QUALITY_HEADER,
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "coin_id": coin_id,
            "source": source,
            "field": field,
            "issue": issue,
        },
    )
