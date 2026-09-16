import pandas as pd

from tradesys.data import cache as bar_cache


def make_bars():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "open": [10.0, 11.0],
            "high": [10.5, 11.5],
            "low": [9.5, 10.5],
            "close": [10.2, 11.2],
            "volume": [1000, 1100],
        }
    )


def test_cache_round_trip(tmp_path):
    cache_dir = str(tmp_path)
    bars = make_bars()

    assert bar_cache.load_cached_bars("TEST", cache_dir=cache_dir) is None

    bar_cache.save_bars("TEST", bars, cache_dir=cache_dir)
    loaded = bar_cache.load_cached_bars("TEST", cache_dir=cache_dir)

    assert loaded is not None
    assert list(loaded["close"]) == [10.2, 11.2]


def test_last_cached_date(tmp_path):
    cache_dir = str(tmp_path)
    bar_cache.save_bars("TEST", make_bars(), cache_dir=cache_dir)

    last_date = bar_cache.last_cached_date("TEST", cache_dir=cache_dir)

    assert last_date == pd.Timestamp("2024-01-02")


def test_save_bars_rejects_missing_columns(tmp_path):
    bad = make_bars().drop(columns=["volume"])
    try:
        bar_cache.save_bars("TEST", bad, cache_dir=str(tmp_path))
        assert False, "expected ValueError"
    except ValueError:
        pass
