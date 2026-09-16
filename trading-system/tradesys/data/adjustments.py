"""Back-adjustment of OHLCV bars for stock splits and dividends.

Why this exists: an un-adjusted price series has fake discontinuities at
every split (e.g. a 2-for-1 split makes the price "drop" 50% overnight with
no corresponding return) and every ex-dividend date (a real, but
non-price-return, drop). A strategy backtested on raw prices will see these
as trade signals or will misprice returns — this is a classic source of
backtests that look good for the wrong reason. We back-adjust historical
prices onto today's share-count/total-return basis instead of forward-
adjusting, so the *most recent* price always matches the real quote.

Algorithm: walk the bars from most recent to oldest, accumulating a
cumulative multiplier. Each split strictly before "today" divides all
earlier prices by the split ratio; each dividend strictly before "today"
scales all earlier prices by (1 - dividend / prior_raw_close), the standard
total-return back-adjustment used by CRSP/Yahoo-style adjusted-close series.
"""

from __future__ import annotations

import pandas as pd


def adjust_ohlcv(
    bars: pd.DataFrame,
    splits: pd.DataFrame | None = None,
    dividends: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Returns a new DataFrame with split/dividend-adjusted OHLC and volume.

    Args:
        bars: columns [date, open, high, low, close, volume], one row per
            trading day, sorted or not (will be sorted here).
        splits: columns [date, ratio] where ratio is new_shares/old_shares
            (e.g. 2.0 for a 2-for-1 split). Optional.
        dividends: columns [date, amount] with the cash dividend per share
            on its ex-dividend date. Optional.
    """
    df = bars.sort_values("date").reset_index(drop=True).copy()
    df["date"] = pd.to_datetime(df["date"])

    split_by_date: dict[pd.Timestamp, float] = {}
    if splits is not None and len(splits):
        split_by_date = {
            pd.Timestamp(d): float(r) for d, r in zip(splits["date"], splits["ratio"])
        }

    div_by_date: dict[pd.Timestamp, float] = {}
    if dividends is not None and len(dividends):
        div_by_date = {
            pd.Timestamp(d): float(a) for d, a in zip(dividends["date"], dividends["amount"])
        }

    n = len(df)
    factor = 1.0
    adj_close = [0.0] * n
    adj_open = [0.0] * n
    adj_high = [0.0] * n
    adj_low = [0.0] * n
    adj_volume = [0.0] * n

    for i in range(n - 1, -1, -1):
        row_date = df.loc[i, "date"]
        adj_close[i] = df.loc[i, "close"] * factor
        adj_open[i] = df.loc[i, "open"] * factor
        adj_high[i] = df.loc[i, "high"] * factor
        adj_low[i] = df.loc[i, "low"] * factor
        adj_volume[i] = df.loc[i, "volume"] / factor if factor else df.loc[i, "volume"]

        # Update the factor applied to strictly-earlier rows based on any
        # event effective on this row's date.
        ratio = split_by_date.get(row_date)
        if ratio:
            factor /= ratio

        dividend = div_by_date.get(row_date)
        if dividend and i > 0:
            prior_raw_close = df.loc[i - 1, "close"]
            if prior_raw_close > 0:
                factor *= 1 - (dividend / prior_raw_close)

    out = df.copy()
    out["open"] = adj_open
    out["high"] = adj_high
    out["low"] = adj_low
    out["close"] = adj_close
    out["volume"] = adj_volume
    return out
