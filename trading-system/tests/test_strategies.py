import pandas as pd

from tradesys.strategies.buy_and_hold import BuyAndHold
from tradesys.strategies.ma_crossover import MACrossover


def make_bars(closes):
    n = len(closes)
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n),
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1000] * n,
        }
    )


def test_buy_and_hold_is_always_long():
    bars = make_bars([10, 11, 12, 9, 8])
    signals = BuyAndHold().generate_signals(bars)
    assert list(signals) == [1, 1, 1, 1, 1]


def test_ma_crossover_flat_until_slow_window_fills():
    bars = make_bars(list(range(1, 10)))  # 9 bars, slow window needs more
    signals = MACrossover(fast_window=2, slow_window=5).generate_signals(bars)
    assert list(signals[:4]) == [0, 0, 0, 0]  # slow MA(5) not valid until index 4


def test_ma_crossover_goes_long_when_fast_crosses_above_slow():
    # Downtrend then sharp uptrend should flip the fast MA above the slow MA.
    closes = [20, 19, 18, 17, 16, 15, 14, 20, 25, 30, 35, 40]
    bars = make_bars(closes)
    signals = MACrossover(fast_window=2, slow_window=4).generate_signals(bars)
    assert signals.iloc[-1] == 1


def test_ma_crossover_rejects_invalid_windows():
    try:
        MACrossover(fast_window=10, slow_window=5)
        assert False, "expected ValueError"
    except ValueError:
        pass
