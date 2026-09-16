#!/usr/bin/env python3
"""Cross-sectional momentum rotation vs. two fair benchmarks, in-sample only
(holdout untouched). Comparing a rotation strategy against any single
stock's own buy-and-hold (like CSL, which happened to compound ~1000%+) is
not a fair test — the fair comparison is against a PASSIVE, DIVERSIFIED
alternative: (a) buy-and-hold VAS, and (b) an equal-weight buy-and-hold
basket of the same 12 stocks the rotation strategy trades.
"""

from __future__ import annotations

import sys

from tradesys.backtest.engine import run_single_symbol_backtest
from tradesys.backtest.portfolio_engine import run_cross_sectional_momentum_backtest
from tradesys.config import ACCOUNT
from tradesys.data.loader import YFinanceClient, load_symbol_bars
from tradesys.strategies.buy_and_hold import BuyAndHold
from tradesys.universe import UNIVERSE_SYMBOLS, exchange_for


def total_return_pct(final_equity: float, starting_capital: float) -> float:
    return (final_equity / starting_capital - 1) * 100


def main() -> None:
    client = YFinanceClient()
    capital = ACCOUNT.starting_capital_aud

    raw_bars = {}
    for symbol in UNIVERSE_SYMBOLS:
        try:
            result = load_symbol_bars(symbol, exchange=exchange_for(symbol), fallback_client=client)
        except Exception as exc:  # noqa: BLE001
            print(f"{symbol}: FAILED to load: {exc}", file=sys.stderr)
            continue
        raw_bars[symbol] = result.bars

    # Common trading-day calendar across ALL rotation-universe symbols.
    common_dates = None
    for bars in raw_bars.values():
        dates = set(bars["date"])
        common_dates = dates if common_dates is None else common_dates & dates
    common_dates = sorted(common_dates)

    n = len(common_dates)
    split_idx = int(n * 0.8)
    in_sample_end = common_dates[split_idx]
    in_sample_dates = set(common_dates[:split_idx])
    print(f"Common calendar: {n} days across {len(raw_bars)} symbols, in-sample ends {in_sample_end.date()}\n")

    aligned = {}
    for symbol, bars in raw_bars.items():
        sliced = bars[bars["date"].isin(in_sample_dates)].sort_values("date").reset_index(drop=True)
        aligned[symbol] = sliced

    rotation = run_cross_sectional_momentum_backtest(
        aligned, starting_capital=capital, lookback_days=126, rebalance_every_days=21, top_k=3
    )
    rotation_pct = total_return_pct(rotation.final_equity, capital)

    # Benchmark A: equal-weight buy-and-hold basket of the same 12 stocks,
    # over the SAME in-sample window.
    per_stock_capital = capital / len(aligned)
    basket_final_equity = 0.0
    for symbol, bars in aligned.items():
        res = run_single_symbol_backtest(bars, BuyAndHold(), symbol, per_stock_capital)
        basket_final_equity += res.final_equity
    basket_pct = total_return_pct(basket_final_equity, capital)

    print(f"{'Approach':<35}{'Return':>10}{'Trades':>10}")
    print(f"{'Cross-sectional momentum (top 3)':<35}{rotation_pct:>9.1f}%{len(rotation.trade_log):>10}")
    print(f"{'Equal-weight B&H basket (12 stocks)':<35}{basket_pct:>9.1f}%{'1x12':>10}")

    if not raw_bars:
        return
    try:
        vas_result = load_symbol_bars("VAS", exchange="ASX", fallback_client=client)
        vas_bars = vas_result.bars[vas_result.bars["date"].isin(in_sample_dates)].sort_values("date").reset_index(drop=True)
        vas_res = run_single_symbol_backtest(vas_bars, BuyAndHold(), "VAS", capital)
        vas_pct = total_return_pct(vas_res.final_equity, capital)
        print(f"{'VAS buy-and-hold':<35}{vas_pct:>9.1f}%{'1':>10}")
    except Exception as exc:  # noqa: BLE001
        print(f"VAS benchmark FAILED to load: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
