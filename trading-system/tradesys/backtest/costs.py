"""Transaction cost model: brokerage, spread, slippage, FX.

Every cost here works AGAINST the trader (spread/slippage are added to buy
prices and subtracted from sell prices in economic effect, modelled here as
a flat cost charged on both legs) — a backtest that ignores this is the
single easiest way to make a strategy look profitable when it isn't.
"""

from __future__ import annotations

from tradesys.config import COSTS


def trade_cost(notional_aud: float, is_foreign: bool = False) -> dict:
    brokerage = max(COSTS.min_brokerage_aud, notional_aud * COSTS.brokerage_pct_of_notional)
    spread = notional_aud * COSTS.assumed_spread_pct
    slippage = notional_aud * COSTS.assumed_slippage_pct
    fx = notional_aud * COSTS.fx_cost_pct if is_foreign else 0.0
    total = brokerage + spread + slippage + fx
    return {
        "brokerage": brokerage,
        "spread": spread,
        "slippage": slippage,
        "fx": fx,
        "total": total,
    }
