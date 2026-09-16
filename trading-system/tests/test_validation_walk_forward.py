import pandas as pd
import pytest

from tradesys.backtest.engine import run_single_symbol_backtest
from tradesys.strategies.buy_and_hold import BuyAndHold
from tradesys.validation.walk_forward import run_walk_forward, split_into_windows


def make_bars(prices, start="2020-01-01"):
    n = len(prices)
    return pd.DataFrame(
        {
            "date": pd.date_range(start, periods=n),
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1000] * n,
        }
    )


def test_split_into_windows_covers_all_dates_without_overlap():
    dates = list(pd.date_range("2020-01-01", periods=100))
    windows = split_into_windows(dates, n_windows=4)

    assert len(windows) == 4
    assert windows[0][0] == dates[0]
    assert windows[-1][1] == dates[-1]
    # Each window's end should be before (or equal to, at the boundary) the next window's start.
    for (_, end), (next_start, _) in zip(windows[:-1], windows[1:]):
        assert end < next_start


def test_split_into_windows_rejects_too_few_dates():
    dates = list(pd.date_range("2020-01-01", periods=2))
    with pytest.raises(ValueError):
        split_into_windows(dates, n_windows=5)


def test_run_walk_forward_returns_one_row_per_window():
    n = 200
    symbol_bars = {"A": make_bars([100 + i * 0.05 for i in range(n)])}

    def run_bh(window_bars, capital):
        return run_single_symbol_backtest(window_bars["A"], BuyAndHold(), "A", capital)

    result = run_walk_forward(symbol_bars, run_bh, starting_capital=1000, n_windows=4)

    assert len(result) == 4
    assert set(result.columns) == {"window_start", "window_end", "return_pct", "trades"}
