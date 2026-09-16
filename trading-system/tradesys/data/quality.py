"""Basic data-quality guard: detect and cut off implausible price history.

Found by inspecting real IVV.AX data: Yahoo Finance's history for that
ASX-cross-listed ETF includes pre-2011 data that doesn't match its actual
ASX listing, with an unexplained ~20x price drop around its real listing
date. auto_adjust=True should already remove real stock-split jumps, so a
huge unexplained single-day move is a sign of spliced/bad source data, not
a real corporate event — the fix is to cut the series off at the last such
jump and keep only the data after it, not to try to "explain" the jump.

This is a blunt instrument, not a full data-vendor reconciliation: it only
catches a single dominant discontinuity per symbol. Good enough to stop the
worst case (a multi-year block of garbage silently corrupting a backtest)
without pretending to be a general data-quality system.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DEFAULT_MAX_DAILY_JUMP_RATIO = 3.0  # a 3x (or 1/3x) overnight move with no
# explaining split is essentially never a real, legitimate price move.


@dataclass
class TruncationReport:
    truncated: bool
    cut_before: pd.Timestamp | None = None
    jump_ratio: float | None = None
    rows_removed: int = 0


def truncate_before_anomaly(
    bars: pd.DataFrame, max_jump_ratio: float = DEFAULT_MAX_DAILY_JUMP_RATIO
) -> tuple[pd.DataFrame, TruncationReport]:
    """Finds the LAST day-over-day close ratio outside
    [1/max_jump_ratio, max_jump_ratio] and drops every row up to and
    including it, keeping only the (presumed clean) data after it.
    Returns the (possibly unchanged) bars and a report of what happened.
    """
    df = bars.sort_values("date").reset_index(drop=True)
    if len(df) < 2:
        return df, TruncationReport(truncated=False)

    ratios = df["close"] / df["close"].shift(1)
    is_anomalous = (ratios > max_jump_ratio) | (ratios < 1 / max_jump_ratio)
    anomalous_idx = df.index[is_anomalous.fillna(False)]

    if len(anomalous_idx) == 0:
        return df, TruncationReport(truncated=False)

    last_anomaly = anomalous_idx[-1]
    cleaned = df.iloc[last_anomaly:].reset_index(drop=True)
    report = TruncationReport(
        truncated=True,
        cut_before=df.loc[last_anomaly, "date"],
        jump_ratio=float(ratios.loc[last_anomaly]),
        rows_removed=last_anomaly,
    )
    return cleaned, report
