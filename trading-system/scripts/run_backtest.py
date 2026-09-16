#!/usr/bin/env python3
"""Runs buy-and-hold vs MA-crossover on the configured universe and prints a
plain comparison. This is the first real end-to-end run of the system —
see README.md for what "beating the benchmark" actually needs to mean
before anything here is trusted as a basis for real trades.
"""

from __future__ import annotations

import sys

from tradesys.backtest.engine import run_single_symbol_backtest
from tradesys.config import ACCOUNT
from tradesys.data.loader import YFinanceClient, load_symbol_bars
from tradesys.strategies.buy_and_hold import BuyAndHold
from tradesys.strategies.ma_crossover import MACrossover
from tradesys.universe import BENCHMARK_SYMBOLS, UNIVERSE_SYMBOLS, exchange_for


def total_return_pct(final_equity: float, starting_capital: float) -> float:
    return (final_equity / starting_capital - 1) * 100


def main() -> None:
    yfinance_client = YFinanceClient()
    symbols = [*BENCHMARK_SYMBOLS, *UNIVERSE_SYMBOLS]

    print(f"{'Symbol':<8}{'Bars':>6}{'B&H %':>10}{'MA(20/50) %':>14}{'MA trades':>11}")
    for symbol in symbols:
        try:
            result = load_symbol_bars(symbol, exchange=exchange_for(symbol), fallback_client=yfinance_client)
        except Exception as exc:  # noqa: BLE001
            print(f"{symbol:<8} FAILED to load: {exc}", file=sys.stderr)
            continue

        bars = result.bars
        if len(bars) < 60:
            print(f"{symbol:<8} skipped: only {len(bars)} bars available")
            continue

        bh = run_single_symbol_backtest(bars, BuyAndHold(), symbol, ACCOUNT.starting_capital_aud)
        ma = run_single_symbol_backtest(bars, MACrossover(20, 50), symbol, ACCOUNT.starting_capital_aud)

        bh_pct = total_return_pct(bh.final_equity, ACCOUNT.starting_capital_aud)
        ma_pct = total_return_pct(ma.final_equity, ACCOUNT.starting_capital_aud)
        ma_trades = len(ma.trade_log)

        print(f"{symbol:<8}{len(bars):>6}{bh_pct:>9.1f}%{ma_pct:>13.1f}%{ma_trades:>11}")


if __name__ == "__main__":
    main()
