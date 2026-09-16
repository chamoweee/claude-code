"""Cash/position ledger used during a backtest run (and reusable for the
paper-trading executor, since the accounting is identical either way)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Position:
    qty: int
    avg_cost: float


@dataclass
class Portfolio:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    trade_log: list[dict] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)

    def buy(self, date, symbol: str, price: float, qty: int, cost: float) -> None:
        if qty <= 0:
            return
        spend = price * qty + cost
        if spend > self.cash + 1e-6:
            raise ValueError(f"Insufficient cash: need {spend:.2f}, have {self.cash:.2f}")
        self.cash -= spend
        pos = self.positions.get(symbol)
        if pos is None:
            self.positions[symbol] = Position(qty=qty, avg_cost=price)
        else:
            total_cost = pos.avg_cost * pos.qty + price * qty
            pos.qty += qty
            pos.avg_cost = total_cost / pos.qty
        self.trade_log.append(
            {"date": date, "symbol": symbol, "side": "buy", "qty": qty, "price": price, "cost": cost, "realized_pnl": None}
        )

    def sell(self, date, symbol: str, price: float, qty: int, cost: float) -> float:
        pos = self.positions.get(symbol)
        if pos is None or qty > pos.qty:
            raise ValueError(f"Cannot sell {qty} of {symbol}: position is {pos.qty if pos else 0}")
        proceeds = price * qty - cost
        realized_pnl = proceeds - pos.avg_cost * qty
        self.cash += proceeds
        pos.qty -= qty
        if pos.qty == 0:
            del self.positions[symbol]
        self.trade_log.append(
            {"date": date, "symbol": symbol, "side": "sell", "qty": qty, "price": price, "cost": cost, "realized_pnl": realized_pnl}
        )
        return realized_pnl

    def market_value(self, prices: dict[str, float]) -> float:
        return sum(pos.qty * prices.get(sym, pos.avg_cost) for sym, pos in self.positions.items())

    def mark_to_market(self, date, prices: dict[str, float]) -> float:
        equity = self.cash + self.market_value(prices)
        self.equity_curve.append({"date": date, "equity": equity})
        return equity
