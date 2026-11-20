"""Live crypto broker via CCXT (100+ exchanges). Optional: `pip install ccxt`.

Live trading is OFF unless you pass `live=True` AND set env MONEYMANAGER_LIVE=1.
API keys are read from env vars, never from config files:
    CCXT_API_KEY, CCXT_SECRET, (optional) CCXT_PASSWORD
"""
from __future__ import annotations

import os

from ..models import Fill, Order, Side
from .base import Broker


class CCXTBroker(Broker):
    name = "ccxt"

    def __init__(self, exchange_id: str, live: bool = False, sandbox: bool = True):
        try:
            import ccxt  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("pip install ccxt to use CCXTBroker") from e
        if live and os.environ.get("MONEYMANAGER_LIVE") != "1":
            raise RuntimeError("Refusing live trading: set MONEYMANAGER_LIVE=1 to confirm.")
        self.is_live = live
        klass = getattr(ccxt, exchange_id)
        self.exchange = klass({
            "apiKey": os.environ.get("CCXT_API_KEY", ""),
            "secret": os.environ.get("CCXT_SECRET", ""),
            "password": os.environ.get("CCXT_PASSWORD") or None,
            "enableRateLimit": True,
        })
        if sandbox:
            self.exchange.set_sandbox_mode(True)

    def submit(self, order: Order, price: float, timestamp: str) -> Fill | None:  # pragma: no cover
        if not self.is_live:
            raise RuntimeError("CCXTBroker created with live=False; use PaperBroker for simulation.")
        side = "buy" if order.side is Side.BUY else "sell"
        res = self.exchange.create_order(order.instrument.symbol, "market", side, order.qty)
        filled = float(res.get("filled") or 0)
        if filled <= 0:
            return None
        fee = (res.get("fee") or {}).get("cost") or 0.0
        return Fill(timestamp=timestamp, symbol=order.instrument.symbol, side=order.side,
                    qty=filled, price=float(res.get("average") or price),
                    commission=float(fee), reason=order.reason)

    def positions(self) -> dict[str, float]:  # pragma: no cover
        bal = self.exchange.fetch_balance()
        return {k: float(v) for k, v in (bal.get("total") or {}).items() if v}
