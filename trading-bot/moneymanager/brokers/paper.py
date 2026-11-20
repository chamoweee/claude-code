"""Simulated broker with commissions and slippage. The default for every run."""
from __future__ import annotations

from ..models import Fill, Order, Side
from .base import Broker


class PaperBroker(Broker):
    name = "paper"
    is_live = False

    def submit(self, order: Order, price: float, timestamp: str) -> Fill | None:
        inst = order.instrument
        if order.qty <= 0 or price <= 0:
            return None
        slip = price * inst.slippage_pct
        fill_price = price + slip if order.side is Side.BUY else price - slip
        commission = (order.qty * inst.commission_per_unit
                      + inst.notional(order.qty, fill_price) * inst.commission_pct)
        return Fill(timestamp=timestamp, symbol=inst.symbol, side=order.side, qty=order.qty,
                    price=fill_price, commission=commission, reason=order.reason)
