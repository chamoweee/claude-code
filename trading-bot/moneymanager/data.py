"""Market data: CSV loading and a synthetic generator for offline testing."""
from __future__ import annotations

import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path

from .models import Bar


def load_csv(path: str | Path) -> list[Bar]:
    """Load OHLCV bars. Expects headers: date|timestamp, open, high, low, close[, volume]."""
    bars = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            row = {k.strip().lower(): v for k, v in row.items()}
            ts = row.get("timestamp") or row.get("date") or row.get("time")
            bars.append(Bar(ts, float(row["open"]), float(row["high"]), float(row["low"]),
                            float(row["close"]), float(row.get("volume") or 0)))
    bars.sort(key=lambda b: b.timestamp)
    return bars


def synthetic(start_price: float, n: int = 500, drift: float = 0.0003, vol: float = 0.015,
              seed: int | None = None, start: date = date(2024, 1, 1)) -> list[Bar]:
    """Geometric Brownian motion daily bars with regime-switching drift (gives trends to trade)."""
    rng = random.Random(seed)
    price = start_price
    bars = []
    regime_drift = drift
    for i in range(n):
        if i % 120 == 0:
            regime_drift = drift * rng.choice([-3, -1, 1, 3])
        ret = rng.gauss(regime_drift, vol)
        o = price
        c = max(o * math.exp(ret), 1e-9)
        hi = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        bars.append(Bar((start + timedelta(days=i)).isoformat(), o, hi, lo, c, rng.randint(1_000, 100_000)))
        price = c
    return bars
