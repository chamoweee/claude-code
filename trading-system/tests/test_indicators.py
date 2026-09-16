import pandas as pd

from tradesys.strategies.indicators import atr, bollinger_bands, rolling_high, rolling_low, rsi


def test_rsi_is_100_when_no_losses():
    closes = pd.Series([float(i) for i in range(1, 20)])  # strictly increasing
    values = rsi(closes, period=14)
    assert values.iloc[-1] == 100.0


def test_rsi_is_0_when_no_gains():
    closes = pd.Series([float(i) for i in range(20, 1, -1)])  # strictly decreasing
    values = rsi(closes, period=14)
    assert values.iloc[-1] == 0.0


def test_rsi_nan_before_period_fills():
    closes = pd.Series([float(i) for i in range(1, 10)])
    values = rsi(closes, period=14)
    assert values.isna().all()


def test_bollinger_bands_ordering():
    closes = pd.Series([10, 11, 9, 12, 8, 13, 7, 14, 6, 15, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29], dtype=float)
    middle, upper, lower = bollinger_bands(closes, window=10, num_std=2.0)
    valid = middle.notna()
    assert (upper[valid] >= middle[valid]).all()
    assert (middle[valid] >= lower[valid]).all()


def test_rolling_high_excludes_current_bar():
    closes = pd.Series([1, 2, 3, 100], dtype=float)
    high = rolling_high(closes, window=3)
    # window of the 3 bars PRIOR to index 3 is [1,2,3] -> max 3, not 100.
    assert high.iloc[3] == 3.0


def test_rolling_low_excludes_current_bar():
    closes = pd.Series([10, 9, 8, 0], dtype=float)
    low = rolling_low(closes, window=3)
    assert low.iloc[3] == 8.0


def test_atr_is_zero_for_flat_series():
    bars = pd.DataFrame({"high": [10.0] * 20, "low": [10.0] * 20, "close": [10.0] * 20})
    values = atr(bars, period=14)
    assert values.iloc[-1] == 0.0


def test_atr_rises_with_larger_ranges():
    calm = pd.DataFrame({"high": [10.2] * 20, "low": [9.8] * 20, "close": [10.0] * 20})
    volatile = pd.DataFrame({"high": [12.0] * 20, "low": [8.0] * 20, "close": [10.0] * 20})
    assert atr(volatile, period=14).iloc[-1] > atr(calm, period=14).iloc[-1]


def test_atr_nan_before_period_fills():
    bars = pd.DataFrame({"high": [10.0] * 5, "low": [9.0] * 5, "close": [9.5] * 5})
    values = atr(bars, period=14)
    assert values.isna().all()
