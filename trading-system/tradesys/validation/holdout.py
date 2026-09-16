"""Out-of-sample holdout split.

The last `holdout_frac` of each symbol's history is set aside and must not
be used for strategy design, parameter choice, or comparison while
searching for a better strategy — only for a single final check once a
candidate is chosen on the in-sample portion. Looking at holdout results
repeatedly while iterating defeats the entire purpose (it just becomes a
second in-sample set you've overfit to by hand).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class HoldoutSplit:
    in_sample: pd.DataFrame
    holdout: pd.DataFrame
    split_date: pd.Timestamp


def split_holdout(bars: pd.DataFrame, holdout_frac: float = 0.2) -> HoldoutSplit:
    if not 0 < holdout_frac < 1:
        raise ValueError("holdout_frac must be between 0 and 1")

    df = bars.sort_values("date").reset_index(drop=True)
    split_idx = int(len(df) * (1 - holdout_frac))
    split_idx = max(1, min(split_idx, len(df) - 1))

    in_sample = df.iloc[:split_idx].reset_index(drop=True)
    holdout = df.iloc[split_idx:].reset_index(drop=True)
    return HoldoutSplit(in_sample=in_sample, holdout=holdout, split_date=holdout.iloc[0]["date"])
