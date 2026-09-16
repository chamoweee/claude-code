import pandas as pd

from tradesys.data.quality import truncate_before_anomaly


def make_bars(dates, closes):
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1000] * len(closes),
        }
    )


def test_no_anomaly_leaves_bars_unchanged():
    bars = make_bars(
        ["2024-01-01", "2024-01-02", "2024-01-03"],
        [100.0, 101.0, 99.0],
    )
    out, report = truncate_before_anomaly(bars)

    assert report.truncated is False
    assert len(out) == 3


def test_ivv_like_anomaly_truncates_to_after_the_drop():
    # Mimics the real IVV.AX shape: plausible-looking prices, then an
    # unexplained ~20x drop, then a normal-looking (gradual) series after —
    # no single post-drop day jumps more than 3x, only the drop itself does.
    dates = [
        "2008-01-01", "2009-01-01", "2011-08-20", "2011-08-22",
        "2012-01-01", "2014-01-01", "2018-01-01", "2026-01-01",
    ]
    closes = [131.0, 128.0, 130.0, 5.8, 6.5, 10.0, 20.0, 38.0]
    bars = make_bars(dates, closes)

    out, report = truncate_before_anomaly(bars, max_jump_ratio=3.0)

    assert report.truncated is True
    assert report.rows_removed == 3  # drops the first 3 rows, keeps from the jump day onward
    assert list(out["close"]) == [5.8, 6.5, 10.0, 20.0, 38.0]
    assert report.cut_before == pd.Timestamp("2011-08-22")


def test_uses_the_last_anomaly_when_there_are_multiple():
    # A spike down, a flat stretch, then a second, separate spike up that
    # sticks — the function should cut at the LAST anomalous jump, not the
    # first one it encounters.
    dates = ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04", "2020-01-05"]
    closes = [100.0, 100.0, 5.0, 5.0, 50.0]
    bars = make_bars(dates, closes)

    out, report = truncate_before_anomaly(bars, max_jump_ratio=2.0)

    assert report.cut_before == pd.Timestamp("2020-01-05")
    assert list(out["close"]) == [50.0]


def test_short_series_is_left_alone():
    bars = make_bars(["2024-01-01"], [100.0])
    out, report = truncate_before_anomaly(bars)

    assert report.truncated is False
    assert len(out) == 1
