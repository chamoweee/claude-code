import pandas as pd

from tradesys.strategies.buy_and_hold import BuyAndHold
from tradesys.strategies.ma_crossover import MACrossover
from tradesys.strategies.mean_reversion import MeanReversion
from tradesys.strategies.momentum_breakout import MomentumBreakout


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


def test_mean_reversion_flat_before_indicators_ready():
    bars = make_bars([10] * 15)  # fewer bars than bb_window(20)/rsi_period(14) need
    signals = MeanReversion().generate_signals(bars)
    assert list(signals) == [0] * 15


def test_mean_reversion_enters_on_oversold_and_holds_until_reversion():
    # Sharp decline (oversold trigger) then recovers back to the mean.
    closes = [100.0] * 20 + [90, 80, 70, 65] + [70, 80, 90, 100, 105, 108, 110]
    bars = make_bars(closes)
    signals = MeanReversion(rsi_period=5, bb_window=10).generate_signals(bars)

    # Should be long at some point after the drop, and flat again once it
    # has clearly reverted back above the recent mean.
    assert 1 in list(signals)
    assert signals.iloc[-1] == 0


def test_momentum_breakout_flat_before_indicators_ready():
    bars = make_bars([10] * 15)
    signals = MomentumBreakout(entry_window=20, exit_window=10).generate_signals(bars)
    assert list(signals) == [0] * 15


def test_momentum_breakout_enters_on_new_high_and_exits_on_breakdown():
    flat = [10.0] * 25
    breakout = [11, 12, 13, 14, 15]  # new highs above the prior 20-day range
    breakdown = [10, 9, 8]  # falls below the recent 10-day low
    bars = make_bars(flat + breakout + breakdown)
    signals = MomentumBreakout(entry_window=20, exit_window=10).generate_signals(bars)

    assert 1 in list(signals)
    assert signals.iloc[-1] == 0


def test_momentum_breakout_rejects_invalid_windows():
    try:
        MomentumBreakout(entry_window=5, exit_window=10)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_momentum_breakout_atr_filter_rejects_a_weak_breakout():
    # Calm, tight range (small ATR) followed by a breakout that only just
    # clears the prior high by a hair — real, but tiny relative to noise.
    flat = [10.0, 10.05, 9.95, 10.02, 9.98] * 6  # low-volatility base (30 bars)
    weak_breakout = [10.06]  # clears the prior high, but barely
    bars = make_bars(flat + weak_breakout)

    unfiltered = MomentumBreakout(entry_window=20, exit_window=10).generate_signals(bars)
    filtered = MomentumBreakout(
        entry_window=20, exit_window=10, min_breakout_atr_multiple=5.0
    ).generate_signals(bars)

    assert unfiltered.iloc[-1] == 1
    assert filtered.iloc[-1] == 0


def test_mean_reversion_require_both_is_stricter_than_either():
    # Oversold on RSI only (steady mild decline), never actually breaks the
    # lower Bollinger Band because the decline is smooth, not a sharp spike.
    closes = [100 - 0.5 * i for i in range(30)]
    bars = make_bars(closes)

    either = MeanReversion(rsi_period=10, bb_window=15, require_both_conditions=False).generate_signals(bars)
    both = MeanReversion(rsi_period=10, bb_window=15, require_both_conditions=True).generate_signals(bars)

    assert 1 in list(either)
    assert 1 not in list(both)
