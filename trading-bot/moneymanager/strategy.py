"""Signal generators. Strategies only say *what* to do; the money manager decides *how much*."""
from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Bar, Signal


def atr(bars: list[Bar], period: int) -> float | None:
    if len(bars) < period + 1:
        return None
    trs = []
    for prev, cur in zip(bars[-period - 1:-1], bars[-period:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(trs) / period


class Strategy(ABC):
    warmup = 1

    @abstractmethod
    def on_bar(self, symbol: str, history: list[Bar]) -> Signal | None:
        """history ends with the newest bar. Return a Signal, or None for no change."""


class TrendFollowing(Strategy):
    """Moving-average crossover with an ATR stop. Works on any market with price data."""

    def __init__(self, fast: int = 20, slow: int = 50, atr_period: int = 14, atr_stop_mult: float = 3.0,
                 allow_short: bool = True):
        if fast >= slow:
            raise ValueError("fast must be < slow")
        self.fast, self.slow = fast, slow
        self.atr_period, self.atr_stop_mult = atr_period, atr_stop_mult
        self.allow_short = allow_short
        self.warmup = max(slow, atr_period + 1)

    def on_bar(self, symbol, history):
        if len(history) < self.warmup:
            return None
        closes = [b.close for b in history]
        fast = sum(closes[-self.fast:]) / self.fast
        slow = sum(closes[-self.slow:]) / self.slow
        vol = atr(history, self.atr_period)
        price = closes[-1]
        if vol is None or vol <= 0:
            return None
        if fast > slow:
            return Signal(symbol, 1, strength=1.0, stop_price=price - self.atr_stop_mult * vol,
                          reason=f"fast {fast:.4g} > slow {slow:.4g}")
        if fast < slow and self.allow_short:
            return Signal(symbol, -1, strength=1.0, stop_price=price + self.atr_stop_mult * vol,
                          reason=f"fast {fast:.4g} < slow {slow:.4g}")
        return Signal(symbol, 0, reason="trend down, shorts disabled")


class MeanReversion(Strategy):
    """Buys when price closes `z_entry` std-devs below its mean, exits back at the mean."""

    def __init__(self, lookback: int = 20, z_entry: float = 2.0, atr_period: int = 14,
                 atr_stop_mult: float = 2.5):
        self.lookback, self.z_entry = lookback, z_entry
        self.atr_period, self.atr_stop_mult = atr_period, atr_stop_mult
        self.warmup = max(lookback, atr_period + 1)
        self._state: dict[str, int] = {}

    def on_bar(self, symbol, history):
        if len(history) < self.warmup:
            return None
        closes = [b.close for b in history[-self.lookback:]]
        mean = sum(closes) / len(closes)
        var = sum((c - mean) ** 2 for c in closes) / len(closes)
        sd = var ** 0.5
        if sd == 0:
            return None
        z = (closes[-1] - mean) / sd
        vol = atr(history, self.atr_period) or sd
        state = self._state.get(symbol, 0)
        price = closes[-1]
        if state == 0 and z <= -self.z_entry:
            self._state[symbol] = 1
            return Signal(symbol, 1, strength=min(1.0, abs(z) / (self.z_entry * 1.5)),
                          stop_price=price - self.atr_stop_mult * vol, reason=f"z={z:.2f}")
        if state == 1 and z >= 0:
            self._state[symbol] = 0
            return Signal(symbol, 0, reason=f"reverted z={z:.2f}")
        return None


def build_strategy(cfg: dict) -> Strategy:
    kind = cfg.get("type", "trend")
    params = {k: v for k, v in cfg.items() if k != "type"}
    if kind == "trend":
        return TrendFollowing(**params)
    if kind == "mean_reversion":
        return MeanReversion(**params)
    raise ValueError(f"unknown strategy type: {kind}")


__all__ = ["Strategy", "TrendFollowing", "MeanReversion", "atr", "build_strategy"]
