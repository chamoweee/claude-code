import pandas as pd

from tradesys.backtest.portfolio_engine import run_cross_sectional_momentum_backtest


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


def test_picks_top_k_by_trailing_momentum():
    n = 60
    # A: strong uptrend, B: flat, C: downtrend, D: mild uptrend.
    a = [100 + i for i in range(n)]
    b = [100.0] * n
    c = [100 - i * 0.5 for i in range(n)]
    d = [100 + i * 0.2 for i in range(n)]
    symbol_bars = {"A": make_bars(a), "B": make_bars(b), "C": make_bars(c), "D": make_bars(d)}

    result = run_cross_sectional_momentum_backtest(
        symbol_bars, starting_capital=10_000, lookback_days=20, rebalance_every_days=20, top_k=2
    )

    # Top 2 by trailing momentum should be A (strongest) and D (second).
    first_rebalance = result.rebalance_log[0]
    assert set(first_rebalance["target"]) == {"A", "D"}


def test_goes_partially_to_cash_when_nothing_qualifies():
    n = 40
    # Everything is flat or declining -> no positive momentum anywhere.
    symbol_bars = {
        "A": make_bars([100 - i * 0.1 for i in range(n)]),
        "B": make_bars([100.0] * n),
    }

    result = run_cross_sectional_momentum_backtest(
        symbol_bars, starting_capital=10_000, lookback_days=20, rebalance_every_days=20,
        top_k=2, require_positive_momentum=True,
    )

    assert result.rebalance_log[0]["target"] == []
    assert result.final_equity == 10_000  # never deployed, all cash


def test_execution_happens_at_next_bar_open_not_same_day():
    n = 25
    prices = [100 + i for i in range(n)]
    symbol_bars = {"A": make_bars(prices), "B": make_bars([100.0] * n)}

    result = run_cross_sectional_momentum_backtest(
        symbol_bars, starting_capital=10_000, lookback_days=20, rebalance_every_days=20, top_k=1
    )

    first_trade = result.trade_log.iloc[0]
    rebalance_date = result.rebalance_log[0]["date"]
    # The trade must be dated the day AFTER the rebalance decision date.
    assert first_trade["date"] > rebalance_date


def test_rejects_misaligned_date_indexes():
    a = make_bars([100.0] * 30)
    b = make_bars([100.0] * 29)  # different length -> different date index
    try:
        run_cross_sectional_momentum_backtest({"A": a, "B": b}, starting_capital=1000, lookback_days=5, rebalance_every_days=5)
        assert False, "expected ValueError"
    except ValueError:
        pass
