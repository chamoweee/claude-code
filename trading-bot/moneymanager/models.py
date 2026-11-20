"""Core data types shared across the money manager."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum


class AssetClass(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    CRYPTO = "crypto"
    FOREX = "forex"
    FUTURES = "futures"
    OPTIONS = "options"
    COMMODITY = "commodity"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Instrument:
    """A tradable instrument on any market.

    multiplier: value of a 1.0 price move per unit (e.g. 50 for ES futures, 1 for stocks).
    lot_size:   smallest tradable quantity step (1 share, 0.0001 BTC, 1000 FX units, 1 contract).
    min_qty:    smallest order allowed by the venue.
    allow_short: whether the venue/account lets you sell short.
    """

    symbol: str
    asset_class: AssetClass
    multiplier: float = 1.0
    lot_size: float = 1.0
    min_qty: float = 0.0
    allow_short: bool = False
    commission_per_unit: float = 0.0
    commission_pct: float = 0.0  # fraction of notional, e.g. 0.001 = 10 bps
    slippage_pct: float = 0.0

    def round_qty(self, qty: float) -> float:
        """Round a quantity toward zero to the instrument's lot size."""
        if self.lot_size <= 0:
            return qty
        steps = math.floor(abs(qty) / self.lot_size + 1e-9)
        rounded = steps * self.lot_size
        # Trim float noise for fractional lots (e.g. 0.0001 BTC).
        decimals = max(0, -int(math.floor(math.log10(self.lot_size)))) if self.lot_size < 1 else 0
        rounded = round(rounded, decimals + 2)
        if rounded < self.min_qty:
            return 0.0
        return math.copysign(rounded, qty) if rounded else 0.0

    def notional(self, qty: float, price: float) -> float:
        return abs(qty) * price * self.multiplier


@dataclass(frozen=True)
class Bar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Order:
    instrument: Instrument
    side: Side
    qty: float  # always positive
    reason: str = ""
    stop_price: float | None = None  # protective stop to attach after fill

    @property
    def signed_qty(self) -> float:
        return self.qty if self.side is Side.BUY else -self.qty


@dataclass
class Fill:
    timestamp: str
    symbol: str
    side: Side
    qty: float
    price: float
    commission: float
    reason: str = ""


@dataclass
class Position:
    instrument: Instrument
    qty: float = 0.0  # signed: + long, - short
    avg_price: float = 0.0
    stop_price: float | None = None
    last_price: float = 0.0
    realized_pnl: float = 0.0
    entry_risk: float = 0.0  # money at risk when opened (|entry - stop| * qty * mult)

    @property
    def is_open(self) -> bool:
        return abs(self.qty) > 1e-12

    @property
    def direction(self) -> int:
        return 0 if not self.is_open else (1 if self.qty > 0 else -1)

    @property
    def market_value(self) -> float:
        return self.qty * self.last_price * self.instrument.multiplier

    @property
    def unrealized_pnl(self) -> float:
        return self.qty * (self.last_price - self.avg_price) * self.instrument.multiplier

    @property
    def open_risk(self) -> float:
        """Money lost if the stop is hit from the current price (0 if no stop)."""
        if not self.is_open or self.stop_price is None:
            return self.notional
        loss = (self.last_price - self.stop_price) * self.qty * self.instrument.multiplier
        return max(loss, 0.0)

    @property
    def notional(self) -> float:
        return abs(self.market_value)


@dataclass
class Signal:
    """A strategy's view on one instrument.

    direction: +1 long, -1 short, 0 flat/exit.
    strength:  0..1 conviction, scales position size.
    stop_price: protective stop level, used for risk-based sizing.
    """

    symbol: str
    direction: int
    strength: float = 1.0
    stop_price: float | None = None
    reason: str = ""
    meta: dict = field(default_factory=dict)
