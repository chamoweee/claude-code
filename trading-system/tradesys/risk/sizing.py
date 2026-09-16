"""Fee-aware position sizing: risk a fixed fraction of equity per trade,
based on distance to stop-loss, not on conviction or "how much I feel like
buying". ASX shares trade in whole units, so quantities are floored.
"""

from __future__ import annotations

import math

from tradesys.config import RISK


def position_size(
    equity_aud: float,
    entry_price: float,
    stop_price: float,
    cash_available_aud: float,
    risk_pct: float = RISK.max_risk_per_trade_pct,
) -> int:
    """Returns whole shares to buy, sized so a stop-out costs ~risk_pct of
    equity, and never sized beyond what cash_available_aud can afford."""
    if entry_price <= 0 or stop_price >= entry_price:
        return 0

    risk_per_share = entry_price - stop_price
    risk_budget = equity_aud * risk_pct
    risk_sized_qty = math.floor(risk_budget / risk_per_share)

    affordable_qty = math.floor(cash_available_aud / entry_price)

    return max(0, min(risk_sized_qty, affordable_qty))
