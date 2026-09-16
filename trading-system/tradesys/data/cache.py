"""Local on-disk cache for daily OHLCV bars, so we don't re-fetch (and burn
API quota) on every run. One CSV per symbol under DATA_CACHE_DIR.
"""

from __future__ import annotations

import os

import pandas as pd

from tradesys.config import DATA_CACHE_DIR

REQUIRED_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def _cache_path(symbol: str, cache_dir: str = DATA_CACHE_DIR) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    safe_symbol = symbol.replace("/", "_")
    return os.path.join(cache_dir, f"{safe_symbol}.csv")


def load_cached_bars(symbol: str, cache_dir: str = DATA_CACHE_DIR) -> pd.DataFrame | None:
    path = _cache_path(symbol, cache_dir)
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    return df[REQUIRED_COLUMNS]


def save_bars(symbol: str, bars: pd.DataFrame, cache_dir: str = DATA_CACHE_DIR) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in bars.columns]
    if missing:
        raise ValueError(f"bars is missing required columns: {missing}")
    path = _cache_path(symbol, cache_dir)
    bars.sort_values("date")[REQUIRED_COLUMNS].to_csv(path, index=False)


def last_cached_date(symbol: str, cache_dir: str = DATA_CACHE_DIR) -> pd.Timestamp | None:
    cached = load_cached_bars(symbol, cache_dir)
    if cached is None or cached.empty:
        return None
    return cached["date"].max()
