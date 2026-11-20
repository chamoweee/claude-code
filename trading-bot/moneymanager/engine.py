"""The money manager engine: data → strategy signal → sizing → risk gate → broker → accounting."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .brokers.base import Broker
from .models import Bar, Fill, Instrument, Order, Side, Signal
from .portfolio import Portfolio
from .risk import RiskManager
from .sizing import Sizer
from .strategy import Strategy, atr

log = logging.getLogger("moneymanager")


@dataclass
class Market:
    instrument: Instrument
    bars: list[Bar]
    strategy: Strategy


@dataclass
class EngineEvent:
    timestamp: str
    symbol: str
    kind: str  # fill | rejected | stop | halt
    detail: str


@dataclass
class MoneyManager:
    portfolio: Portfolio
    sizer: Sizer
    risk: RiskManager
    broker: Broker
    # Fraction of equity budgeted to each asset class for sizing (e.g. {"crypto": 0.25}).
    # Classes not listed get `default_allocation`.
    allocations: dict[str, float] = field(default_factory=dict)
    default_allocation: float = 1.0
    trail_stops: bool = True
    events: list[EngineEvent] = field(default_factory=list)

    # ------------------------------------------------------------------ helpers
    def _event(self, ts: str, symbol: str, kind: str, detail: str) -> None:
        self.events.append(EngineEvent(ts, symbol, kind, detail))
        log.info("%s %-10s %-8s %s", ts, symbol, kind, detail)

    def _execute(self, order: Order, price: float, ts: str, bypass_risk: bool = False) -> Fill | None:
        if not bypass_risk:
            decision = self.risk.check(order, self.portfolio, price)
            if not decision.approved:
                self._event(ts, order.instrument.symbol, "rejected", "; ".join(decision.reasons))
                return None
            if decision.approved_qty < order.qty:
                self._event(ts, order.instrument.symbol, "resized",
                            f"{order.qty:g} -> {decision.approved_qty:g} ({'; '.join(decision.reasons)})")
                order.qty = decision.approved_qty
        fill = self.broker.submit(order, price, ts)
        if fill is None:
            return None
        self.portfolio.apply_fill(fill, order.instrument, stop_price=order.stop_price)
        self._event(ts, fill.symbol, "fill",
                    f"{fill.side.value} {fill.qty:g} @ {fill.price:.6g} ({order.reason})")
        return fill

    def budget_equity(self, inst: Instrument) -> float:
        w = self.allocations.get(inst.asset_class.value, self.default_allocation)
        return self.portfolio.equity * w

    # ------------------------------------------------------------------ stops
    def check_stop(self, inst: Instrument, bar: Bar) -> None:
        pos = self.portfolio.position(inst)
        if not pos.is_open or pos.stop_price is None:
            return
        stop = pos.stop_price
        if pos.qty > 0 and bar.low <= stop:
            px = min(bar.open, stop)  # gap-through fills at the open
            self._execute(Order(inst, Side.SELL, abs(pos.qty), reason=f"stop {stop:.6g}"), px, bar.timestamp,
                          bypass_risk=True)
            self._event(bar.timestamp, inst.symbol, "stop", f"long stopped at {px:.6g}")
        elif pos.qty < 0 and bar.high >= stop:
            px = max(bar.open, stop)
            self._execute(Order(inst, Side.BUY, abs(pos.qty), reason=f"stop {stop:.6g}"), px, bar.timestamp,
                          bypass_risk=True)
            self._event(bar.timestamp, inst.symbol, "stop", f"short stopped at {px:.6g}")

    # ------------------------------------------------------------------ signals
    def on_signal(self, inst: Instrument, signal: Signal, bar: Bar, volatility: float | None) -> None:
        pos = self.portfolio.position(inst)
        price = bar.close
        ts = bar.timestamp

        if signal.direction == 0:
            if pos.is_open:
                side = Side.SELL if pos.qty > 0 else Side.BUY
                self._execute(Order(inst, side, abs(pos.qty), reason=signal.reason or "exit"), price, ts)
            return

        if pos.direction == signal.direction:
            # Already positioned: only ratchet the stop in our favour.
            if self.trail_stops and signal.stop_price is not None and pos.stop_price is not None:
                if (pos.qty > 0 and signal.stop_price > pos.stop_price) or \
                   (pos.qty < 0 and signal.stop_price < pos.stop_price):
                    pos.stop_price = signal.stop_price
            return

        target = self.sizer.size(equity=self.budget_equity(inst), instrument=inst, price=price,
                                 signal=signal, volatility=volatility)
        target = abs(inst.round_qty(target)) * signal.direction
        delta = target - pos.qty
        if abs(delta) <= 0 or target == 0:
            if pos.is_open:  # can't size a new trade but the old direction is wrong: exit
                side = Side.SELL if pos.qty > 0 else Side.BUY
                self._execute(Order(inst, side, abs(pos.qty), reason="flip unsized; exit"), price, ts)
            return
        side = Side.BUY if delta > 0 else Side.SELL
        self._execute(Order(inst, side, abs(delta), reason=signal.reason, stop_price=signal.stop_price), price, ts)


class PortfolioStrategy:
    """A strategy that decides for all markets at once (e.g. the AI agent).

    decide() returns {symbol: Signal}. Symbols left out mean "hold / no change".
    """

    warmup = 1

    def decide(self, timestamp: str, history: dict[str, list[Bar]], mm: "MoneyManager",
               instruments: dict[str, Instrument]) -> dict[str, Signal]:
        raise NotImplementedError


class Engine:
    """Runs markets bar-by-bar through a MoneyManager. Used for backtests, paper and live trading.

    Each market can have its own per-symbol Strategy, or set `strategy=None` and let a single
    PortfolioStrategy (like the AI agent) decide for all of them every `decide_every` bars.
    """

    def __init__(self, mm: MoneyManager, markets: list[Market], vol_period: int = 14,
                 portfolio_strategy: PortfolioStrategy | None = None, decide_every: int = 1):
        self.mm = mm
        self.markets = {m.instrument.symbol: m for m in markets}
        self.vol_period = vol_period
        self.portfolio_strategy = portfolio_strategy
        self.decide_every = max(1, decide_every)
        self.history: dict[str, list[Bar]] = {s: [] for s in self.markets}
        self._halt_handled = False
        self._steps = 0
        self.last_timestamp: str | None = None

    def step(self, ts: str, bars: dict[str, Bar]) -> None:
        """Process one timestamp's bars ({symbol: bar}). Safe to call live, one bar at a time."""
        pf = self.mm.portfolio
        pf.on_new_bar_time(ts)
        for sym, bar in bars.items():
            m = self.markets[sym]
            pf.mark(sym, bar.open)
            self.mm.check_stop(m.instrument, bar)
            pf.mark(sym, bar.close)
            self.history[sym].append(bar)

        self.mm.risk.update(pf)
        if self.mm.risk.halted and not self._halt_handled:
            self._halt_handled = True
            self.mm._event(ts, "*", "halt", self.mm.risk.halt_reason + " — flattening all positions")
            for p in pf.open_positions():
                side = Side.SELL if p.qty > 0 else Side.BUY
                self.mm._execute(Order(p.instrument, side, abs(p.qty), reason="kill switch"),
                                 p.last_price, ts, bypass_risk=True)

        for sym, bar in bars.items():
            m = self.markets[sym]
            if m.strategy is None:
                continue
            hist = self.history[sym]
            sig = m.strategy.on_bar(sym, hist)
            if sig is not None:
                self.mm.on_signal(m.instrument, sig, bar, atr(hist, self.vol_period))

        ps = self.portfolio_strategy
        if ps is not None and not self.mm.risk.halted and self._steps % self.decide_every == 0:
            ready = {s: h for s, h in self.history.items()
                     if len(h) >= ps.warmup and s in bars and self.markets[s].strategy is None}
            if ready:
                instruments = {s: self.markets[s].instrument for s in ready}
                for sym, sig in ps.decide(ts, ready, self.mm, instruments).items():
                    if sym in ready:
                        self.mm.on_signal(instruments[sym], sig, ready[sym][-1],
                                          atr(ready[sym], self.vol_period))
        self._steps += 1
        self.last_timestamp = ts
        pf.record_equity(ts)

    def run(self) -> Portfolio:
        # Union of all timestamps so markets with different calendars (24/7 crypto vs weekday stocks) align.
        by_ts: dict[str, dict[str, Bar]] = {}
        for sym, m in self.markets.items():
            for b in m.bars:
                by_ts.setdefault(b.timestamp, {})[sym] = b
        for ts in sorted(by_ts):
            self.step(ts, by_ts[ts])
        return self.mm.portfolio
