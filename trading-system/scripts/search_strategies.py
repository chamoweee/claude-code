#!/usr/bin/env python3
"""Searches a handful of a-priori lower-frequency strategy variants against
buy-and-hold, using ONLY the in-sample 80% of each symbol's history.

This is a search step, not a final verdict — the holdout 20% (see
tradesys/validation/holdout.py) is deliberately never touched here. Once a
candidate looks genuinely better in-sample, run it ONCE against holdout
(scripts/check_holdout.py) and report that number as final, win or lose —
looking at holdout repeatedly while tuning defeats its purpose.

Variants tested are chosen for a specific, stated reason (lower trade
frequency to survive fixed brokerage costs, or a conviction filter to only
take larger moves) — not a blind grid search for whatever looks best.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from tradesys.backtest.engine import run_single_symbol_backtest
from tradesys.config import ACCOUNT
from tradesys.data.loader import YFinanceClient, load_symbol_bars
from tradesys.strategies.base import Strategy
from tradesys.strategies.buy_and_hold import BuyAndHold
from tradesys.strategies.ma_crossover import MACrossover
from tradesys.strategies.mean_reversion import MeanReversion
from tradesys.strategies.momentum_breakout import MomentumBreakout
from tradesys.universe import BENCHMARK_SYMBOLS, UNIVERSE_SYMBOLS, exchange_for
from tradesys.validation.holdout import split_holdout


@dataclass
class Candidate:
    label: str
    reason: str
    build: callable


CANDIDATES = [
    Candidate(
        "MA(50,200)",
        "Classic long-horizon trend-follow ('golden cross') — far fewer trades than MA(20,50).",
        lambda: MACrossover(50, 200),
    ),
    Candidate(
        "Breakout(55,20)",
        "Classic Turtle System-2 style channel — wider window, fewer/bigger breakouts.",
        lambda: MomentumBreakout(55, 20),
    ),
    Candidate(
        "Breakout(20,10,atr>=1.5)",
        "Original windows, but only takes breakouts clearing the range by >=1.5 ATR.",
        lambda: MomentumBreakout(20, 10, min_breakout_atr_multiple=1.5),
    ),
    Candidate(
        "MeanRev(and)",
        "Original windows, but requires RSI AND price both oversold, not either.",
        lambda: MeanReversion(require_both_conditions=True),
    ),
]


def total_return_pct(final_equity: float, starting_capital: float) -> float:
    return (final_equity / starting_capital - 1) * 100


def main() -> None:
    client = YFinanceClient()
    symbols = [*BENCHMARK_SYMBOLS, *UNIVERSE_SYMBOLS]
    capital = ACCOUNT.starting_capital_aud

    # bh_return, {label: [returns...]}, {label: [trade_counts...]}
    bh_returns: list[float] = []
    candidate_returns: dict[str, list[float]] = {c.label: [] for c in CANDIDATES}
    candidate_trades: dict[str, list[int]] = {c.label: [] for c in CANDIDATES}
    wins: dict[str, int] = {c.label: 0 for c in CANDIDATES}
    n_symbols = 0

    for symbol in symbols:
        try:
            result = load_symbol_bars(symbol, exchange=exchange_for(symbol), fallback_client=client)
        except Exception as exc:  # noqa: BLE001
            print(f"{symbol}: FAILED to load: {exc}", file=sys.stderr)
            continue

        if len(result.bars) < 300:
            continue

        split = split_holdout(result.bars, holdout_frac=0.2)
        in_sample = split.in_sample
        n_symbols += 1

        bh = run_single_symbol_backtest(in_sample, BuyAndHold(), symbol, capital)
        bh_pct = total_return_pct(bh.final_equity, capital)
        bh_returns.append(bh_pct)

        for c in CANDIDATES:
            strat: Strategy = c.build()
            res = run_single_symbol_backtest(in_sample, strat, symbol, capital)
            pct = total_return_pct(res.final_equity, capital)
            candidate_returns[c.label].append(pct)
            candidate_trades[c.label].append(len(res.trade_log))
            if pct > bh_pct:
                wins[c.label] += 1

    print(f"In-sample only ({n_symbols} symbols, holdout 20% untouched)\n")
    print(f"Buy & Hold: avg return {sum(bh_returns)/len(bh_returns):.1f}%\n")
    print(f"{'Candidate':<26}{'Avg return':>12}{'Beats B&H':>12}{'Avg trades':>12}   Reason")
    for c in CANDIDATES:
        returns = candidate_returns[c.label]
        trades = candidate_trades[c.label]
        avg_return = sum(returns) / len(returns) if returns else float("nan")
        avg_trades = sum(trades) / len(trades) if trades else float("nan")
        print(
            f"{c.label:<26}{avg_return:>11.1f}%{wins[c.label]:>9}/{n_symbols:<3}{avg_trades:>11.1f}   {c.reason}"
        )


if __name__ == "__main__":
    main()
