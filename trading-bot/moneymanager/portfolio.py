"""Portfolio accounting: cash, positions, equity, drawdown."""
from __future__ import annotations

from collections import defaultdict

from .models import AssetClass, Fill, Instrument, Position, Side


class Portfolio:
    def __init__(self, starting_cash: float):
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []
        self.high_water_mark = starting_cash
        self.day_start_equity = starting_cash
        self.current_day: str | None = None
        self.equity_curve: list[tuple[str, float]] = []
        self.closed_trades: list[float] = []  # realized pnl per round trip

    # ---------- queries ----------
    def position(self, instrument: Instrument) -> Position:
        pos = self.positions.get(instrument.symbol)
        if pos is None:
            pos = Position(instrument=instrument)
            self.positions[instrument.symbol] = pos
        return pos

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions.values() if p.is_open]

    @property
    def equity(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions.values())

    @property
    def gross_exposure(self) -> float:
        return sum(p.notional for p in self.open_positions())

    @property
    def drawdown(self) -> float:
        """Current drawdown from the high-water mark as a fraction (0.1 = -10%)."""
        if self.high_water_mark <= 0:
            return 0.0
        return max(0.0, 1.0 - self.equity / self.high_water_mark)

    @property
    def daily_pnl_pct(self) -> float:
        if self.day_start_equity <= 0:
            return 0.0
        return self.equity / self.day_start_equity - 1.0

    def exposure_by_class(self) -> dict[AssetClass, float]:
        out: dict[AssetClass, float] = defaultdict(float)
        for p in self.open_positions():
            out[p.instrument.asset_class] += p.notional
        return dict(out)

    def total_open_risk(self) -> float:
        return sum(p.open_risk for p in self.open_positions())

    # ---------- updates ----------
    def mark(self, symbol: str, price: float) -> None:
        pos = self.positions.get(symbol)
        if pos is not None:
            pos.last_price = price

    def on_new_bar_time(self, timestamp: str) -> None:
        day = timestamp[:10]
        if day != self.current_day:
            self.current_day = day
            self.day_start_equity = self.equity

    def record_equity(self, timestamp: str) -> None:
        eq = self.equity
        self.high_water_mark = max(self.high_water_mark, eq)
        self.equity_curve.append((timestamp, eq))

    def apply_fill(self, fill: Fill, instrument: Instrument, stop_price: float | None = None) -> None:
        pos = self.position(instrument)
        signed = fill.qty if fill.side is Side.BUY else -fill.qty
        mult = instrument.multiplier

        # Cash moves by full notional (works for cash equities/crypto; for futures/FX this is
        # an accounting simplification — equity is still correct because market_value offsets it).
        self.cash -= signed * fill.price * mult
        self.cash -= fill.commission
        pos.realized_pnl -= fill.commission

        if not pos.is_open or (pos.qty > 0) == (signed > 0):
            # Opening or adding.
            new_qty = pos.qty + signed
            pos.avg_price = (pos.avg_price * abs(pos.qty) + fill.price * abs(signed)) / abs(new_qty)
            pos.qty = new_qty
            if stop_price is not None:
                pos.stop_price = stop_price
                pos.entry_risk = abs(pos.avg_price - stop_price) * abs(pos.qty) * mult
        else:
            # Reducing, closing, or flipping.
            closing = min(abs(signed), abs(pos.qty))
            pnl = closing * (fill.price - pos.avg_price) * mult * (1 if pos.qty > 0 else -1)
            pos.realized_pnl += pnl
            self.closed_trades.append(pnl - fill.commission)
            remaining = pos.qty + signed
            if abs(remaining) < 1e-12:
                pos.qty, pos.avg_price, pos.stop_price, pos.entry_risk = 0.0, 0.0, None, 0.0
            elif (remaining > 0) != (pos.qty > 0):
                # Flipped through zero: the leftover is a fresh position at the fill price.
                pos.qty, pos.avg_price = remaining, fill.price
                pos.stop_price = stop_price
                pos.entry_risk = abs(fill.price - stop_price) * abs(remaining) * mult if stop_price else 0.0
            else:
                pos.qty = remaining
        pos.last_price = fill.price
        self.fills.append(fill)
