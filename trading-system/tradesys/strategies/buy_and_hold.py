"""Buy-and-hold benchmark. Every other strategy must beat this, after fees,
on out-of-sample data, or it doesn't get to go live — see config.GO_LIVE."""

from __future__ import annotations

import pandas as pd

from tradesys.strategies.base import Strategy


class BuyAndHold(Strategy):
    name = "buy_and_hold"
    sizing_mode = "full_capital"
    # No stop-loss for a benchmark — it is not a strategy for us to manage risk on,
    # it is the number we're required to beat.
    stop_loss_pct = 1.0

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series([1] * len(bars), index=bars.index)
