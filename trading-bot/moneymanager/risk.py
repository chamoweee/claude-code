"""Risk manager: the gate every order passes through before reaching a broker."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Order
from .portfolio import Portfolio


@dataclass
class RiskLimits:
    max_drawdown: float = 0.20          # halt all new risk beyond this drawdown from peak
    daily_loss_limit: float = 0.03      # stop opening trades for the day after -3%
    max_positions: int = 10
    max_position_pct: float = 0.20      # max notional per position as fraction of equity
    max_gross_leverage: float = 2.0     # sum of |notional| / equity
    max_total_open_risk: float = 0.06   # sum of stop-risk across positions / equity
    # Per-asset-class caps on gross notional as fraction of equity. Missing class = no cap.
    class_caps: dict[str, float] = field(default_factory=dict)
    # Per-asset-class leverage allowed for a single position (e.g. futures/forex > 1).
    class_max_position_pct: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "RiskLimits":
        return cls(**d)


@dataclass
class RiskDecision:
    approved_qty: float
    reasons: list[str]

    @property
    def approved(self) -> bool:
        return self.approved_qty > 0


class RiskManager:
    def __init__(self, limits: RiskLimits):
        self.limits = limits
        self.halted = False
        self.halt_reason = ""

    # Kill switch -----------------------------------------------------------
    def update(self, portfolio: Portfolio) -> None:
        """Call once per bar. Trips the kill switch on max drawdown."""
        if not self.halted and portfolio.drawdown >= self.limits.max_drawdown:
            self.halted = True
            self.halt_reason = f"max drawdown {portfolio.drawdown:.1%} >= {self.limits.max_drawdown:.0%}"

    def reset(self) -> None:
        """Manual reset after a human has reviewed the halt."""
        self.halted = False
        self.halt_reason = ""

    def daily_limit_hit(self, portfolio: Portfolio) -> bool:
        return portfolio.daily_pnl_pct <= -self.limits.daily_loss_limit

    # Order check -----------------------------------------------------------
    def check(self, order: Order, portfolio: Portfolio, price: float) -> RiskDecision:
        """Approve, shrink, or reject an order. Risk-reducing orders are always allowed."""
        inst = order.instrument
        pos = portfolio.position(inst)
        current = pos.qty
        target = current + order.signed_qty
        reasons: list[str] = []

        reduces = abs(target) < abs(current) and (target == 0 or (target > 0) == (current > 0))
        if reduces:
            return RiskDecision(order.qty, ["risk-reducing"])

        if self.halted:
            return RiskDecision(0.0, [f"halted: {self.halt_reason}"])
        if self.daily_limit_hit(portfolio):
            return RiskDecision(0.0, [f"daily loss limit {self.limits.daily_loss_limit:.0%} hit"])
        if target < 0 and not inst.allow_short:
            # Allow closing the long part of a flip, block the short part.
            if current > 0:
                return RiskDecision(current, ["shorting not allowed; closing long only"])
            return RiskDecision(0.0, [f"shorting not allowed for {inst.symbol}"])

        equity = portfolio.equity
        if equity <= 0:
            return RiskDecision(0.0, ["non-positive equity"])

        opening_new = not pos.is_open or (current > 0) != (target > 0)
        if opening_new and len(portfolio.open_positions()) >= self.limits.max_positions and not pos.is_open:
            return RiskDecision(0.0, [f"max positions {self.limits.max_positions} reached"])

        # The new exposure portion of this order (beyond any part that closes an existing position).
        if (current > 0) != (target > 0) and pos.is_open:
            new_units = abs(target)          # flip: close all, open |target|
            close_units = abs(current)
        else:
            new_units = abs(target) - abs(current)
            close_units = 0.0

        unit_notional = price * inst.multiplier
        allowed_new = new_units

        # 1) per-position notional cap
        cls = inst.asset_class.value
        pos_cap_pct = self.limits.class_max_position_pct.get(cls, self.limits.max_position_pct)
        max_units_pos = pos_cap_pct * equity / unit_notional
        existing_same_dir = 0.0 if close_units else abs(current)
        if existing_same_dir + allowed_new > max_units_pos:
            allowed_new = max(0.0, max_units_pos - existing_same_dir)
            reasons.append(f"capped by position limit {pos_cap_pct:.0%}")

        # 2) asset-class cap
        if cls in self.limits.class_caps:
            used = portfolio.exposure_by_class().get(inst.asset_class, 0.0)
            if close_units:
                used -= abs(current) * unit_notional
            room = self.limits.class_caps[cls] * equity - used
            max_units_cls = max(0.0, room / unit_notional)
            if allowed_new > max_units_cls:
                allowed_new = max_units_cls
                reasons.append(f"capped by {cls} class cap {self.limits.class_caps[cls]:.0%}")

        # 3) gross leverage
        gross = portfolio.gross_exposure - close_units * unit_notional
        room = self.limits.max_gross_leverage * equity - gross
        max_units_lev = max(0.0, room / unit_notional)
        if allowed_new > max_units_lev:
            allowed_new = max_units_lev
            reasons.append(f"capped by gross leverage {self.limits.max_gross_leverage}x")

        # 4) total open risk (stop distance based)
        if order.stop_price is not None:
            per_unit_risk = abs(price - order.stop_price) * inst.multiplier
            if per_unit_risk > 0:
                open_risk = portfolio.total_open_risk()
                if close_units:
                    open_risk -= pos.open_risk
                room = self.limits.max_total_open_risk * equity - open_risk
                max_units_risk = max(0.0, room / per_unit_risk)
                if allowed_new > max_units_risk:
                    allowed_new = max_units_risk
                    reasons.append(f"capped by total open risk {self.limits.max_total_open_risk:.0%}")

        allowed_new = abs(inst.round_qty(allowed_new))
        approved = close_units + allowed_new
        if allowed_new <= 0 and not close_units:
            return RiskDecision(0.0, reasons or ["size rounds to zero"])
        return RiskDecision(approved, reasons or ["ok"])


__all__ = ["RiskLimits", "RiskManager", "RiskDecision"]
