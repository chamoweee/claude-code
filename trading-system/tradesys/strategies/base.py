"""Strategy plug-in interface.

A strategy only decides a target position (1 = fully in, 0 = flat) as of
each bar's CLOSE — it never sees future bars. The backtest engine is what
enforces next-bar execution (trade at the following bar's open), so a
correctly-written strategy naturally avoids look-ahead bias as long as
generate_signals only uses bars.loc[:i] to produce signal[i].
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

import pandas as pd

from tradesys.config import RISK


class Strategy(ABC):
    name: str = "unnamed"
    # 'risk_per_trade': size so a stop-out costs max_risk_per_trade_pct of equity.
    # 'full_capital': deploy all available cash (used for the buy-and-hold benchmark).
    sizing_mode: Literal["risk_per_trade", "full_capital"] = "risk_per_trade"
    stop_loss_pct: float = 0.08

    @abstractmethod
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        """bars has columns [date, open, high, low, close, volume], sorted
        ascending by date. Returns a same-length Series of 0/1, aligned by
        position (not by date value) with `bars`."""
        raise NotImplementedError
