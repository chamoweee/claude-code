import pandas as pd
import pytest

from tradesys.validation.holdout import split_holdout


def make_bars(n):
    return pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=n),
            "open": range(n),
            "high": range(n),
            "low": range(n),
            "close": range(n),
            "volume": [100] * n,
        }
    )


def test_split_respects_fraction():
    bars = make_bars(100)
    result = split_holdout(bars, holdout_frac=0.2)

    assert len(result.in_sample) == 80
    assert len(result.holdout) == 20


def test_holdout_is_strictly_after_in_sample():
    bars = make_bars(100)
    result = split_holdout(bars, holdout_frac=0.2)

    assert result.in_sample["date"].max() < result.holdout["date"].min()
    assert result.split_date == result.holdout["date"].min()


def test_rejects_invalid_fraction():
    bars = make_bars(10)
    with pytest.raises(ValueError):
        split_holdout(bars, holdout_frac=0)
    with pytest.raises(ValueError):
        split_holdout(bars, holdout_frac=1)


def test_no_row_is_duplicated_or_dropped():
    bars = make_bars(37)
    result = split_holdout(bars, holdout_frac=0.3)

    assert len(result.in_sample) + len(result.holdout) == 37
