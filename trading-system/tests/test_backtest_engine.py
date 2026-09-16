import pandas as pd

from tradesys.backtest.engine import run_single_symbol_backtest
from tradesys.strategies.base import Strategy
from tradesys.strategies.buy_and_hold import BuyAndHold


def make_bars(opens, closes):
    n = len(opens)
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n),
            "open": opens,
            "high": [max(o, c) for o, c in zip(opens, closes)],
            "low": [min(o, c) for o, c in zip(opens, closes)],
            "close": closes,
            "volume": [1000] * n,
        }
    )


class AlwaysFlat(Strategy):
    name = "always_flat"
    sizing_mode = "full_capital"

    def generate_signals(self, bars):
        return pd.Series([0] * len(bars), index=bars.index)


def test_no_signal_means_no_trades_and_flat_equity():
    bars = make_bars(opens=[10, 11, 12, 13], closes=[10, 11, 12, 13])
    result = run_single_symbol_backtest(bars, AlwaysFlat(), "TEST", starting_capital=1000.0)

    assert result.trade_log.empty
    assert result.final_equity == 1000.0
    assert len(result.equity_curve) == len(bars)


def test_buy_and_hold_executes_at_next_bar_open_not_same_day():
    # Day 0 close triggers the signal; entry must happen at day 1's open (11),
    # never at day 0's own open (10) or close (10.5).
    bars = make_bars(opens=[10, 11, 12, 13], closes=[10.5, 11.5, 12.5, 13.5])
    result = run_single_symbol_backtest(bars, BuyAndHold(), "TEST", starting_capital=1000.0)

    first_trade = result.trade_log.iloc[0]
    assert first_trade["side"] == "buy"
    assert first_trade["price"] == 11.0  # day 1's open, not day 0's
    assert first_trade["date"] == bars.iloc[1]["date"]


def test_equity_curve_on_entry_day_excludes_the_not_yet_executed_trade():
    bars = make_bars(opens=[10, 11, 12, 13], closes=[10.5, 11.5, 12.5, 13.5])
    result = run_single_symbol_backtest(bars, BuyAndHold(), "TEST", starting_capital=1000.0)

    day0_equity = result.equity_curve.iloc[0]["equity"]
    # Nothing has executed yet as of day 0's close — still all cash.
    assert day0_equity == 1000.0


def test_fees_reduce_final_equity_versus_a_zero_cost_run():
    bars = make_bars(opens=[10] * 10, closes=[10] * 10)
    result = run_single_symbol_backtest(bars, BuyAndHold(), "TEST", starting_capital=1000.0)

    # Flat prices with real fees charged on entry should leave slightly less
    # than the starting capital, not exactly the starting capital.
    assert result.final_equity < 1000.0
