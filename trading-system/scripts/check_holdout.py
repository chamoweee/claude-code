#!/usr/bin/env python3
"""THE one-shot holdout check for the (lookback=126, rebalance=126, top_k=3)
cross-sectional momentum config -- the candidate that passed both the
sensitivity sweep and the walk-forward check in round 4.

This script is meant to be run ONCE per candidate. Its whole point is that
the result is reported as final, win or lose -- re-running it with a
different config after seeing this number defeats the purpose of a
holdout set entirely (it just becomes a second in-sample set you've
overfit to by hand).
"""

from __future__ import annotations

import sys

from tradesys.backtest.engine import run_single_symbol_backtest
from tradesys.backtest.portfolio_engine import run_cross_sectional_momentum_backtest
from tradesys.config import ACCOUNT
from tradesys.data.loader import YFinanceClient, load_symbol_bars
from tradesys.strategies.buy_and_hold import BuyAndHold
from tradesys.universe import UNIVERSE_SYMBOLS


def total_return_pct(final_equity: float, starting_capital: float) -> float:
    return (final_equity / starting_capital - 1) * 100


def main() -> None:
    client = YFinanceClient()
    capital = ACCOUNT.starting_capital_aud

    raw_bars = {}
    for symbol in UNIVERSE_SYMBOLS:
        try:
            result = load_symbol_bars(symbol, exchange="ASX", fallback_client=client)
        except Exception as exc:  # noqa: BLE001
            print(f"{symbol}: FAILED to load: {exc}", file=sys.stderr)
            continue
        raw_bars[symbol] = result.bars

    common_dates = None
    for bars in raw_bars.values():
        dates = set(bars["date"])
        common_dates = dates if common_dates is None else common_dates & dates
    common_dates = sorted(common_dates)
    split_idx = int(len(common_dates) * 0.8)
    holdout_dates = set(common_dates[split_idx:])
    print(f"Holdout window: {common_dates[split_idx].date()} to {common_dates[-1].date()} "
          f"({len(holdout_dates)} trading days, {len(raw_bars)} symbols)\n")

    holdout_bars = {
        symbol: bars[bars["date"].isin(holdout_dates)].sort_values("date").reset_index(drop=True)
        for symbol, bars in raw_bars.items()
    }

    rotation = run_cross_sectional_momentum_backtest(
        holdout_bars, starting_capital=capital, lookback_days=126, rebalance_every_days=126, top_k=3
    )
    rotation_pct = total_return_pct(rotation.final_equity, capital)

    per_stock_capital = capital / len(holdout_bars)
    basket_final_equity = 0.0
    for symbol, bars in holdout_bars.items():
        res = run_single_symbol_backtest(bars, BuyAndHold(), symbol, per_stock_capital)
        basket_final_equity += res.final_equity
    basket_pct = total_return_pct(basket_final_equity, capital)

    vas_result = load_symbol_bars("VAS", exchange="ASX", fallback_client=client)
    vas_bars = vas_result.bars[vas_result.bars["date"].isin(holdout_dates)].sort_values("date").reset_index(drop=True)
    vas_res = run_single_symbol_backtest(vas_bars, BuyAndHold(), "VAS", capital)
    vas_pct = total_return_pct(vas_res.final_equity, capital)

    print("=== HOLDOUT RESULT (final, not re-run) ===")
    print(f"{'Cross-sectional momentum (126,126,top3)':<42}{rotation_pct:>9.1f}%  ({len(rotation.trade_log)} trades)")
    print(f"{'Equal-weight B&H basket (12 stocks)':<42}{basket_pct:>9.1f}%")
    print(f"{'VAS buy-and-hold':<42}{vas_pct:>9.1f}%")


if __name__ == "__main__":
    main()
