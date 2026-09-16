"""Moving-average crossover: long while the fast MA is above the slow MA,
flat otherwise. Simple and easy to reason about — a good first baseline,
not a claim that it's a good strategy. It needs to beat buy-and-hold after
fees on held-out data before that changes."""

from __future__ import annotations

import pandas as pd

from tradesys.strategies.base import Strategy


class MACrossover(Strategy):
    name = "ma_crossover"
    sizing_mode = "risk_per_trade"

    def __init__(self, fast_window: int = 20, slow_window: int = 50, stop_loss_pct: float = 0.08):
        if fast_window >= slow_window:
            raise ValueError("fast_window must be smaller than slow_window")
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.stop_loss_pct = stop_loss_pct
        self.name = f"ma_crossover_{fast_window}_{slow_window}"

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        fast_ma = close.rolling(self.fast_window, min_periods=self.fast_window).mean()
        slow_ma = close.rolling(self.slow_window, min_periods=self.slow_window).mean()
        # Until the slow MA has enough history, there is no valid signal —
        # stay flat rather than let a NaN comparison silently resolve to False
        # in a way that's easy to misread as an intentional "no" signal.
        signal = (fast_ma > slow_ma) & slow_ma.notna()
        return signal.astype(int)
