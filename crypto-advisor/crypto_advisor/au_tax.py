"""Australian tax considerations for the advisory layer.

General information only -- NOT tax advice. Always show the disclaimer
alongside any SELL/TRIM figures this module produces.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

DISCLAIMER = (
    "General information only, not tax advice. Cost-base and CGT-discount figures are "
    "estimates based on the data in portfolio.yaml; confirm with a registered tax agent "
    "before acting. Swapping one crypto asset for another is a CGT disposal event in "
    "Australia -- it is not tax-free just because no AUD changed hands."
)

SWAP_NOTE = "Swapping this coin for another crypto asset is a CGT event in Australia, the same as selling for AUD."


@dataclass
class TaxContext:
    unrealised_gain_aud: float
    unrealised_gain_pct: float
    days_held: int
    cgt_discount_eligible: bool
    cgt_discount_date: str
    within_discount_warning_window: bool
    days_until_discount: int | None


def compute_tax_context(cost_base_aud: float, units: float, current_price_aud: float, purchase_date: str, config: dict) -> TaxContext:
    tcfg = config["au_tax"]
    current_value = units * current_price_aud
    gain = current_value - cost_base_aud
    gain_pct = (gain / cost_base_aud * 100) if cost_base_aud else 0.0

    purchased = datetime.strptime(purchase_date, "%Y-%m-%d").date()
    today = date.today()
    days_held = (today - purchased).days
    discount_days = tcfg["cgt_discount_days"]
    discount_date = purchased.fromordinal(purchased.toordinal() + discount_days)
    eligible = days_held >= discount_days
    days_until = None if eligible else (discount_date - today).days
    within_warning = (not eligible) and days_until is not None and days_until <= tcfg["cgt_discount_warning_window_days"]

    return TaxContext(
        unrealised_gain_aud=round(gain, 2),
        unrealised_gain_pct=round(gain_pct, 2),
        days_held=days_held,
        cgt_discount_eligible=eligible,
        cgt_discount_date=discount_date.isoformat(),
        within_discount_warning_window=within_warning,
        days_until_discount=days_until,
    )


def exchange_fee_bps(exchange: str, config: dict) -> float:
    fees = config["au_tax"]["exchange_fees_bps"]
    return fees.get(exchange, fees["default"])


def net_trade_amount_aud(gross_aud: float, exchange: str, config: dict) -> float:
    """Gross trade value minus estimated exchange fee + spread (bps)."""
    bps = exchange_fee_bps(exchange, config)
    return round(gross_aud * (1 - bps / 10_000), 2)
