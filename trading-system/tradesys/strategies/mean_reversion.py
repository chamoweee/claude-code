"""Mean reversion: go long when the market looks oversold (RSI below a
threshold, or price below the lower Bollinger Band), hold until it reverts
back toward the mean (RSI recovers, or price back above the middle band).

This is a state machine, not a per-bar snapshot rule — "oversold today" is
an entry trigger, not a instruction to be flat again the moment it's no
longer true. The exit condition is deliberately different and looser than
the entry condition.

`require_both_conditions` is an optional conviction filter: entering only
when RSI AND price are both signalling oversold (not either alone) is a
strictly rarer, stronger-dislocation event than either condition on its
own — fewer trades, each a bigger anomaly.
"""

from __future__ import annotations

import pandas as pd

from tradesys.strategies.base import Strategy
from tradesys.strategies.indicators import bollinger_bands, rsi


class MeanReversion(Strategy):
    name = "mean_reversion"
    sizing_mode = "risk_per_trade"

    def __init__(
        self,
        rsi_period: int = 14,
        oversold_rsi: float = 30.0,
        exit_rsi: float = 50.0,
        bb_window: int = 20,
        bb_std: float = 2.0,
        stop_loss_pct: float = 0.06,
        require_both_conditions: bool = False,
    ):
        self.rsi_period = rsi_period
        self.oversold_rsi = oversold_rsi
        self.exit_rsi = exit_rsi
        self.bb_window = bb_window
        self.bb_std = bb_std
        self.stop_loss_pct = stop_loss_pct
        self.require_both_conditions = require_both_conditions
        mode = "and" if require_both_conditions else "or"
        self.name = f"mean_reversion_{rsi_period}_{bb_window}_{mode}"

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        rsi_values = rsi(close, self.rsi_period)
        middle_band, _, lower_band = bollinger_bands(close, self.bb_window, self.bb_std)

        ready = rsi_values.notna() & middle_band.notna()
        rsi_oversold = rsi_values < self.oversold_rsi
        price_oversold = close < lower_band
        if self.require_both_conditions:
            oversold = rsi_oversold & price_oversold
        else:
            oversold = rsi_oversold | price_oversold
        reverted = (rsi_values > self.exit_rsi) | (close >= middle_band)

        signal = [0] * len(bars)
        state = 0
        for i in range(len(bars)):
            if not ready.iloc[i]:
                signal[i] = 0
                continue
            if state == 0 and oversold.iloc[i]:
                state = 1
            elif state == 1 and reverted.iloc[i]:
                state = 0
            signal[i] = state

        return pd.Series(signal, index=bars.index)
