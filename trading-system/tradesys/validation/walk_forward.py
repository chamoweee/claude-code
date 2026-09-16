"""Walk-forward consistency check: split the (in-sample) date range into
several sequential, non-overlapping windows and run the SAME fixed
strategy configuration on each one independently, rather than judging it
on one long aggregate run. A real edge should show up as "mostly positive
across windows" — a strategy that owes its entire return to one standout
window and is flat or negative in the others is a strategy that got lucky
once, not one with a repeatable edge.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd


def split_into_windows(dates: list[pd.Timestamp], n_windows: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if n_windows < 1:
        raise ValueError("n_windows must be at least 1")
    n = len(dates)
    if n < n_windows:
        raise ValueError(f"not enough dates ({n}) to split into {n_windows} windows")

    boundaries = [int(round(i * n / n_windows)) for i in range(n_windows + 1)]
    windows = []
    for start_idx, end_idx in zip(boundaries[:-1], boundaries[1:]):
        end_idx = max(end_idx, start_idx + 1)
        windows.append((dates[start_idx], dates[min(end_idx, n) - 1]))
    return windows


def run_walk_forward(
    symbol_bars: dict[str, pd.DataFrame],
    run_backtest_fn: Callable[[dict[str, pd.DataFrame], float], object],
    starting_capital: float,
    n_windows: int = 4,
) -> pd.DataFrame:
    """`run_backtest_fn(window_symbol_bars, starting_capital)` must return
    an object with `.final_equity` and `.trade_log` (both the single-symbol
    and portfolio engine results already satisfy this)."""
    any_symbol = next(iter(symbol_bars.values()))
    all_dates = sorted(any_symbol["date"].unique())
    windows = split_into_windows(all_dates, n_windows)

    rows = []
    for window_start, window_end in windows:
        window_bars = {
            symbol: bars[(bars["date"] >= window_start) & (bars["date"] <= window_end)].reset_index(drop=True)
            for symbol, bars in symbol_bars.items()
        }
        result = run_backtest_fn(window_bars, starting_capital)
        return_pct = (result.final_equity / starting_capital - 1) * 100
        rows.append(
            {
                "window_start": window_start,
                "window_end": window_end,
                "return_pct": return_pct,
                "trades": len(result.trade_log),
            }
        )
    return pd.DataFrame(rows)
