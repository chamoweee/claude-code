import pandas as pd

from tradesys.data.adjustments import adjust_ohlcv


def make_bars(dates, closes):
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1000] * len(closes),
        }
    )


def test_split_adjustment_scales_prior_prices_down():
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    closes = [100.0, 100.0, 50.0]  # 2-for-1 split effective on the 3rd day
    bars = make_bars(dates, closes)
    splits = pd.DataFrame({"date": ["2024-01-03"], "ratio": [2.0]})

    out = adjust_ohlcv(bars, splits=splits)

    assert out.loc[0, "close"] == 50.0
    assert out.loc[1, "close"] == 50.0
    assert out.loc[2, "close"] == 50.0  # most recent price is never touched


def test_dividend_adjustment_scales_prior_prices_down():
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    closes = [100.0, 98.0, 98.0]  # $2 dividend goes ex on day 3
    bars = make_bars(dates, closes)
    dividends = pd.DataFrame({"date": ["2024-01-03"], "amount": [2.0]})

    out = adjust_ohlcv(bars, dividends=dividends)

    expected_factor = 1 - (2.0 / 98.0)
    assert out.loc[0, "close"] == 100.0 * expected_factor
    assert out.loc[1, "close"] == 98.0 * expected_factor
    assert out.loc[2, "close"] == 98.0  # unaffected — most recent bar


def test_no_events_leaves_prices_unchanged():
    dates = ["2024-01-01", "2024-01-02"]
    closes = [10.0, 11.0]
    bars = make_bars(dates, closes)

    out = adjust_ohlcv(bars)

    assert list(out["close"]) == closes


def test_volume_is_inverse_adjusted_for_splits():
    dates = ["2024-01-01", "2024-01-02"]
    closes = [100.0, 50.0]
    bars = make_bars(dates, closes)
    bars["volume"] = [1000, 2000]
    splits = pd.DataFrame({"date": ["2024-01-02"], "ratio": [2.0]})

    out = adjust_ohlcv(bars, splits=splits)

    # Pre-split volume should be scaled up to reflect the post-split share count.
    assert out.loc[0, "volume"] == 2000
    assert out.loc[1, "volume"] == 2000
