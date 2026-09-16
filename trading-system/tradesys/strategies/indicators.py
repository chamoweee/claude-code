"""Shared technical indicator calculations, kept separate from any one
strategy so they can be reused and unit-tested independently."""

from __future__ import annotations

import pandas as pd


def rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI. NaN until `period` bars of history exist."""
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def bollinger_bands(closes: pd.Series, window: int = 20, num_std: float = 2.0):
    """Returns (middle, upper, lower) bands, NaN until `window` bars exist."""
    middle = closes.rolling(window, min_periods=window).mean()
    std = closes.rolling(window, min_periods=window).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return middle, upper, lower


def rolling_high(series: pd.Series, window: int) -> pd.Series:
    """Highest value over the PRIOR `window` bars, excluding the current
    one — shifted so a breakout comparison isn't tautological (today's own
    high always satisfies `today >= max(including today)`)."""
    return series.rolling(window, min_periods=window).max().shift(1)


def rolling_low(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).min().shift(1)
