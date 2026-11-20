"""Broker interface. Implement this to connect any exchange or brokerage."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Fill, Order


class Broker(ABC):
    name = "base"
    is_live = False

    @abstractmethod
    def submit(self, order: Order, price: float, timestamp: str) -> Fill | None:
        """Execute (or route) an order. Return the fill, or None if not filled."""

    def positions(self) -> dict[str, float]:
        """Venue-reported positions, for reconciliation. Optional."""
        return {}
