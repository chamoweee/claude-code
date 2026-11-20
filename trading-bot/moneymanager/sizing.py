"""Position sizing models.

Every sizer answers one question: given equity, a signal and market data, how many units?
The result is a *target* absolute quantity before risk limits and lot rounding.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod

from .models import Instrument, Signal


class Sizer(ABC):
    @abstractmethod
    def size(self, *, equity: float, instrument: Instrument, price: float, signal: Signal,
             volatility: float | None) -> float:
        """Return an unsigned target quantity."""


class FixedFractionalRisk(Sizer):
    """Risk a fixed fraction of equity per trade, measured entry→stop.

    qty = equity * risk_per_trade * strength / (|price - stop| * multiplier)
    Falls back to `fallback_stop_vol_mult * volatility` as the stop distance when no stop is given.
    """

    def __init__(self, risk_per_trade: float = 0.01, fallback_stop_vol_mult: float = 2.0):
        if not 0 < risk_per_trade <= 0.1:
            raise ValueError("risk_per_trade should be in (0, 0.1]")
        self.risk_per_trade = risk_per_trade
        self.fallback_stop_vol_mult = fallback_stop_vol_mult

    def size(self, *, equity, instrument, price, signal, volatility):
        if signal.stop_price is not None:
            stop_dist = abs(price - signal.stop_price)
        elif volatility:
            stop_dist = self.fallback_stop_vol_mult * volatility
        else:
            return 0.0
        if stop_dist <= 0:
            return 0.0
        risk_money = equity * self.risk_per_trade * max(0.0, min(signal.strength, 1.0))
        return risk_money / (stop_dist * instrument.multiplier)


class VolatilityTarget(Sizer):
    """Size so each position contributes a target daily volatility as a fraction of equity.

    volatility: expected absolute price move per bar (e.g. ATR or stdev of price changes).
    """

    def __init__(self, target_vol_per_position: float = 0.005):
        self.target = target_vol_per_position

    def size(self, *, equity, instrument, price, signal, volatility):
        if not volatility or volatility <= 0:
            return 0.0
        money_vol = equity * self.target * max(0.0, min(signal.strength, 1.0))
        return money_vol / (volatility * instrument.multiplier)


class FractionalKelly(Sizer):
    """Kelly criterion on observed win rate / payoff, scaled down (default quarter-Kelly).

    Kelly fraction f* = W - (1 - W) / R, where W = win rate, R = avg win / avg loss.
    The resulting fraction of equity is turned into risk money and sized against the stop.
    Capped at `max_risk` per trade so a lucky streak can't blow up sizing.
    """

    def __init__(self, win_rate: float, payoff_ratio: float, fraction: float = 0.25,
                 max_risk: float = 0.02, fallback_stop_vol_mult: float = 2.0):
        self.win_rate = win_rate
        self.payoff_ratio = payoff_ratio
        self.fraction = fraction
        self.max_risk = max_risk
        self.fallback_stop_vol_mult = fallback_stop_vol_mult

    @property
    def risk_fraction(self) -> float:
        if self.payoff_ratio <= 0:
            return 0.0
        kelly = self.win_rate - (1 - self.win_rate) / self.payoff_ratio
        return max(0.0, min(kelly * self.fraction, self.max_risk))

    def update_from_trades(self, pnls: list[float], min_trades: int = 30) -> None:
        """Refresh W and R from realized trade results once there's enough history."""
        if len(pnls) < min_trades:
            return
        wins = [p for p in pnls if p > 0]
        losses = [-p for p in pnls if p < 0]
        if not wins or not losses:
            return
        self.win_rate = len(wins) / len(pnls)
        self.payoff_ratio = (sum(wins) / len(wins)) / (sum(losses) / len(losses))

    def size(self, *, equity, instrument, price, signal, volatility):
        f = self.risk_fraction
        if f <= 0:
            return 0.0
        if signal.stop_price is not None:
            stop_dist = abs(price - signal.stop_price)
        elif volatility:
            stop_dist = self.fallback_stop_vol_mult * volatility
        else:
            return 0.0
        if stop_dist <= 0 or math.isnan(stop_dist):
            return 0.0
        return equity * f * max(0.0, min(signal.strength, 1.0)) / (stop_dist * instrument.multiplier)


def build_sizer(cfg: dict) -> Sizer:
    kind = cfg.get("type", "fixed_fractional")
    params = {k: v for k, v in cfg.items() if k != "type"}
    if kind == "fixed_fractional":
        return FixedFractionalRisk(**params)
    if kind == "volatility_target":
        return VolatilityTarget(**params)
    if kind == "kelly":
        return FractionalKelly(**params)
    raise ValueError(f"unknown sizer type: {kind}")
