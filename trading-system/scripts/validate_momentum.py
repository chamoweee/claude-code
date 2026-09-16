#!/usr/bin/env python3
"""Validates the cross-sectional momentum candidate from round 3: a
parameter-sensitivity sweep (is the result stable across nearby configs, or
a spike at one lucky combination?) and a walk-forward check (does the best-
looking config hold up across multiple sequential sub-periods, or did it
live off one standout window?). In-sample only -- holdout still untouched.
"""

from __future__ import annotations

import sys

from tradesys.backtest.portfolio_engine import run_cross_sectional_momentum_backtest
from tradesys.config import ACCOUNT
from tradesys.data.loader import YFinanceClient, load_symbol_bars
from tradesys.universe import UNIVERSE_SYMBOLS
from tradesys.validation.sensitivity import summarize_stability, sweep_cross_sectional_momentum
from tradesys.validation.walk_forward import run_walk_forward


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
    in_sample_dates = set(common_dates[:split_idx])

    aligned = {
        symbol: bars[bars["date"].isin(in_sample_dates)].sort_values("date").reset_index(drop=True)
        for symbol, bars in raw_bars.items()
    }

    print("=== Parameter sensitivity sweep (in-sample) ===")
    sweep = sweep_cross_sectional_momentum(
        aligned,
        starting_capital=capital,
        lookback_grid=[63, 126, 189],
        rebalance_grid=[21, 63, 126, 189],
        top_k=3,
    )
    print(sweep.to_string(index=False))
    print()
    summary = summarize_stability(sweep)
    for k, v in summary.items():
        print(f"  {k}: {v:.1f}" if isinstance(v, float) else f"  {k}: {v}")

    print("\n=== Walk-forward check: lookback=126, rebalance=126 across 4 sequential windows ===")

    def run_semiannual(window_bars, cap):
        return run_cross_sectional_momentum_backtest(
            window_bars, starting_capital=cap, lookback_days=126, rebalance_every_days=126, top_k=3
        )

    wf = run_walk_forward(aligned, run_semiannual, starting_capital=capital, n_windows=4)
    print(wf.to_string(index=False))


if __name__ == "__main__":
    main()
