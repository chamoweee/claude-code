import pandas as pd
import pytest

from tradesys.data import cache as bar_cache
from tradesys.data.loader import load_symbol_bars


class FakeTwelveData:
    def __init__(self, bars=None, splits=None, dividends=None, raise_error=False):
        self._bars = bars
        self._splits = splits if splits is not None else pd.DataFrame(columns=["date", "ratio"])
        self._dividends = dividends if dividends is not None else pd.DataFrame(columns=["date", "amount"])
        self.raise_error = raise_error

    def get_time_series(self, symbol, exchange, outputsize=5000):
        if self.raise_error:
            raise RuntimeError("simulated Twelve Data outage")
        return self._bars

    def get_splits(self, symbol, exchange):
        return self._splits

    def get_dividends(self, symbol, exchange):
        return self._dividends


class FakeYFinance:
    def __init__(self, bars=None, raise_error=False):
        self._bars = bars
        self.raise_error = raise_error

    def get_time_series(self, symbol, exchange, outputsize=5000):
        if self.raise_error:
            raise RuntimeError("simulated yfinance failure")
        return self._bars


def sample_bars():
    return pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "open": [10.0, 11.0],
            "high": [10.5, 11.5],
            "low": [9.5, 10.5],
            "close": [10.2, 11.2],
            "volume": [1000, 1100],
        }
    )


def test_uses_cache_when_present(tmp_path):
    cache_dir = str(tmp_path)
    bar_cache.save_bars("BHP", pd.DataFrame(
        {"date": pd.to_datetime(["2024-01-01"]), "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]}
    ), cache_dir=cache_dir)

    result = load_symbol_bars("BHP", cache_dir=cache_dir, primary_client=FakeTwelveData(raise_error=True))

    assert result.source == "cache"


def test_falls_back_to_primary_when_cache_empty(tmp_path):
    result = load_symbol_bars(
        "BHP",
        cache_dir=str(tmp_path),
        primary_client=FakeTwelveData(bars=sample_bars()),
    )

    assert result.source == "twelve_data"
    assert len(result.bars) == 2


def test_falls_back_to_yfinance_when_primary_fails(tmp_path):
    result = load_symbol_bars(
        "BHP",
        cache_dir=str(tmp_path),
        primary_client=FakeTwelveData(raise_error=True),
        fallback_client=FakeYFinance(bars=sample_bars()),
    )

    assert result.source == "yfinance"


def test_raises_when_every_source_fails(tmp_path):
    with pytest.raises(RuntimeError):
        load_symbol_bars(
            "BHP",
            cache_dir=str(tmp_path),
            primary_client=FakeTwelveData(raise_error=True),
            fallback_client=FakeYFinance(raise_error=True),
        )


def test_force_refresh_bypasses_cache(tmp_path):
    cache_dir = str(tmp_path)
    bar_cache.save_bars("BHP", pd.DataFrame(
        {"date": pd.to_datetime(["2024-01-01"]), "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]}
    ), cache_dir=cache_dir)

    result = load_symbol_bars(
        "BHP",
        cache_dir=cache_dir,
        primary_client=FakeTwelveData(bars=sample_bars()),
        force_refresh=True,
    )

    assert result.source == "twelve_data"
    assert len(result.bars) == 2
