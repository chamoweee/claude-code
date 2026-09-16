import pandas as pd

from tradesys.validation.sensitivity import summarize_stability, sweep_cross_sectional_momentum


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


def test_sweep_covers_full_grid():
    n = 300
    symbol_bars = {
        "A": make_bars([100 + i * 0.1 for i in range(n)]),
        "B": make_bars([100 - i * 0.05 for i in range(n)]),
    }

    sweep = sweep_cross_sectional_momentum(
        symbol_bars, starting_capital=10_000, lookback_grid=[20, 40], rebalance_grid=[20, 40], top_k=1
    )

    assert len(sweep) == 4  # 2x2 grid
    assert set(sweep["lookback_days"]) == {20, 40}
    assert set(sweep["rebalance_every_days"]) == {20, 40}


def test_summarize_stability_flags_all_profitable():
    sweep = pd.DataFrame({"return_pct": [5.0, 8.0, 3.0, 10.0]})
    summary = summarize_stability(sweep)

    assert summary["n_combinations"] == 4
    assert summary["n_profitable"] == 4
    assert summary["pct_profitable"] == 100.0


def test_summarize_stability_flags_mostly_unprofitable():
    sweep = pd.DataFrame({"return_pct": [-30.0, -20.0, -10.0, 50.0]})
    summary = summarize_stability(sweep)

    assert summary["n_profitable"] == 1
    assert summary["pct_profitable"] == 25.0
    assert summary["max_return_pct"] == 50.0
