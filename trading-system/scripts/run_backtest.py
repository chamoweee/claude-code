#!/usr/bin/env python3
"""Runs buy-and-hold vs three candidate strategies on the configured
universe and prints a plain comparison. This is the honest first look at
the system end-to-end — see README.md for what "beating the benchmark"
actually needs to mean before anything here is trusted as a basis for real
trades. Numbers are printed as computed, not selected or tuned to look
better.
"""

from __future__ import annotations

import sys

from tradesys.backtest.engine import run_single_symbol_backtest
from tradesys.config import ACCOUNT
from tradesys.data.loader import YFinanceClient, load_symbol_bars
from tradesys.strategies.buy_and_hold import BuyAndHold
from tradesys.strategies.ma_crossover import MACrossover
from tradesys.strategies.mean_reversion import MeanReversion
from tradesys.strategies.momentum_breakout import MomentumBreakout
from tradesys.universe import BENCHMARK_SYMBOLS, UNIVERSE_SYMBOLS, exchange_for


def total_return_pct(final_equity: float, starting_capital: float) -> float:
    return (final_equity / starting_capital - 1) * 100


def main() -> None:
    yfinance_client = YFinanceClient()
    symbols = [*BENCHMARK_SYMBOLS, *UNIVERSE_SYMBOLS]
    force_refresh = "--refresh" in sys.argv

    header = f"{'Symbol':<8}{'Bars':>6}{'B&H %':>9}{'MA %':>9}{'MeanRev %':>11}{'Breakout %':>12}"
    print(header)
    for symbol in symbols:
        try:
            result = load_symbol_bars(
                symbol,
                exchange=exchange_for(symbol),
                fallback_client=yfinance_client,
                force_refresh=force_refresh,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"{symbol:<8} FAILED to load: {exc}", file=sys.stderr)
            continue

        if result.quality and result.quality.truncated:
            print(
                f"  [{symbol}] data quality: cut {result.quality.rows_removed} rows before "
                f"{result.quality.cut_before.date()} (jump ratio {result.quality.jump_ratio:.2f}x)",
                file=sys.stderr,
            )

        bars = result.bars
        if len(bars) < 60:
            print(f"{symbol:<8} skipped: only {len(bars)} bars available")
            continue

        capital = ACCOUNT.starting_capital_aud
        bh = run_single_symbol_backtest(bars, BuyAndHold(), symbol, capital)
        ma = run_single_symbol_backtest(bars, MACrossover(20, 50), symbol, capital)
        mr = run_single_symbol_backtest(bars, MeanReversion(), symbol, capital)
        mb = run_single_symbol_backtest(bars, MomentumBreakout(20, 10), symbol, capital)

        row = (
            f"{symbol:<8}{len(bars):>6}"
            f"{total_return_pct(bh.final_equity, capital):>8.1f}%"
            f"{total_return_pct(ma.final_equity, capital):>8.1f}%"
            f"{total_return_pct(mr.final_equity, capital):>10.1f}%"
            f"{total_return_pct(mb.final_equity, capital):>11.1f}%"
        )
        print(row)


if __name__ == "__main__":
    main()
