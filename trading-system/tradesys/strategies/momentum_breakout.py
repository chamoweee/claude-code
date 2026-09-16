"""Momentum breakout (Donchian-channel style): go long when price breaks
above its prior N-day high, exit when it breaks below its prior M-day low.
Classic trend-following baseline — exit window is intentionally shorter
than the entry window so it gives back less on a reversal.
"""

from __future__ import annotations

import pandas as pd

from tradesys.strategies.base import Strategy
from tradesys.strategies.indicators import rolling_high, rolling_low


class MomentumBreakout(Strategy):
    name = "momentum_breakout"
    sizing_mode = "risk_per_trade"

    def __init__(self, entry_window: int = 20, exit_window: int = 10, stop_loss_pct: float = 0.10):
        if exit_window >= entry_window:
            raise ValueError("exit_window should be shorter than entry_window")
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.stop_loss_pct = stop_loss_pct
        self.name = f"momentum_breakout_{entry_window}_{exit_window}"

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        entry_level = rolling_high(close, self.entry_window)
        exit_level = rolling_low(close, self.exit_window)

        ready = entry_level.notna() & exit_level.notna()
        breakout_up = close > entry_level
        breakdown = close < exit_level

        signal = [0] * len(bars)
        state = 0
        for i in range(len(bars)):
            if not ready.iloc[i]:
                signal[i] = 0
                continue
            if state == 0 and breakout_up.iloc[i]:
                state = 1
            elif state == 1 and breakdown.iloc[i]:
                state = 0
            signal[i] = state

        return pd.Series(signal, index=bars.index)
