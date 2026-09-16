"""Parameter-sensitivity sweep: if a strategy only looks good at one exact
parameter combination and falls apart at its neighbours, that's the
signature of a fluke fit to this particular historical path, not a real
edge. A real edge should look "good-ish" across a neighbourhood of
reasonable parameters, not spike at a single point.
"""

from __future__ import annotations

import pandas as pd

from tradesys.backtest.portfolio_engine import run_cross_sectional_momentum_backtest


def sweep_cross_sectional_momentum(
    symbol_bars: dict[str, pd.DataFrame],
    starting_capital: float,
    lookback_grid: list[int],
    rebalance_grid: list[int],
    top_k: int = 3,
    require_positive_momentum: bool = True,
) -> pd.DataFrame:
    """Runs the cross-sectional momentum backtest across every
    (lookback_days, rebalance_every_days) combination in the grid and
    returns one row per combination. Caller decides what "stable" means —
    this just produces the surface to look at."""
    rows = []
    for lookback in lookback_grid:
        for rebalance in rebalance_grid:
            result = run_cross_sectional_momentum_backtest(
                symbol_bars,
                starting_capital=starting_capital,
                lookback_days=lookback,
                rebalance_every_days=rebalance,
                top_k=top_k,
                require_positive_momentum=require_positive_momentum,
            )
            return_pct = (result.final_equity / starting_capital - 1) * 100
            rows.append(
                {
                    "lookback_days": lookback,
                    "rebalance_every_days": rebalance,
                    "return_pct": return_pct,
                    "trades": len(result.trade_log),
                }
            )
    return pd.DataFrame(rows)


def summarize_stability(sweep: pd.DataFrame) -> dict:
    """A crude but useful stability readout: how much of the grid is
    profitable, and the spread of outcomes. Wide spread / few profitable
    cells alongside one standout winner is a red flag, not a green light."""
    returns = sweep["return_pct"]
    return {
        "n_combinations": len(sweep),
        "n_profitable": int((returns > 0).sum()),
        "pct_profitable": float((returns > 0).mean() * 100),
        "median_return_pct": float(returns.median()),
        "min_return_pct": float(returns.min()),
        "max_return_pct": float(returns.max()),
        "std_return_pct": float(returns.std()),
    }
