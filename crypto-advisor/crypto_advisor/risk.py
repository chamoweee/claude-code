"""Hard risk gates applied on top of `signals.score_coin` output. These can
only downgrade an action (never upgrade), and are the only place trade
sizing, entry/exit levels and AU tax context are attached.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .au_tax import DISCLAIMER, SWAP_NOTE, TaxContext, compute_tax_context, net_trade_amount_aud
from .classify import CORE, REVENUE_GENERATING, SPECULATIVE, Classification
from .config import Holding
from .metrics import CoinMetrics
from .signals import ADD, BUY, HOLD, SELL, TRIM, WATCH, SignalResult
from .universe import UniverseCoin

_TIER_RANK = {CORE: 3, REVENUE_GENERATING: 2, SPECULATIVE: 1}


@dataclass
class FinalAction:
    coin_id: str
    action: str
    original_signal_action: str
    confidence: str
    score: float
    held: bool
    suggested_aud: Optional[float] = None
    suggested_units: Optional[float] = None
    entry_price_aud: Optional[float] = None
    stop_price_aud: Optional[float] = None
    reasons: list[str] = field(default_factory=list)
    tax_context: Optional[TaxContext] = None
    tax_disclaimer: Optional[str] = None


def portfolio_weights(holdings: list[Holding], prices_by_id: dict[str, float], cash_aud: float) -> tuple[dict[str, float], float]:
    values = {h.coin_id: h.units * prices_by_id.get(h.coin_id, 0.0) for h in holdings}
    total = sum(values.values()) + cash_aud
    weights = {cid: (v / total * 100 if total else 0.0) for cid, v in values.items()}
    return weights, total


def speculative_allocation_pct(holdings: list[Holding], prices_by_id: dict[str, float], classifications_by_id: dict[str, Classification], total_value: float) -> float:
    if total_value <= 0:
        return 0.0
    spec_value = sum(
        h.units * prices_by_id.get(h.coin_id, 0.0)
        for h in holdings
        if classifications_by_id.get(h.coin_id) and classifications_by_id[h.coin_id].tier == SPECULATIVE
    )
    return spec_value / total_value * 100


def core_allocation_pct(holdings: list[Holding], prices_by_id: dict[str, float], classifications_by_id: dict[str, Classification], total_value: float) -> float:
    if total_value <= 0:
        return 0.0
    core_value = sum(
        h.units * prices_by_id.get(h.coin_id, 0.0)
        for h in holdings
        if classifications_by_id.get(h.coin_id) and classifications_by_id[h.coin_id].tier == CORE
    )
    return core_value / total_value * 100


def rolling_high_since(coin: UniverseCoin, purchase_date: Optional[str]) -> Optional[float]:
    if not coin.daily_prices:
        return None
    if not purchase_date:
        return max(p for _, p in coin.daily_prices)
    purchase_ts = datetime.strptime(purchase_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000
    relevant = [p for ts, p in coin.daily_prices if ts >= purchase_ts]
    if not relevant:
        relevant = [p for _, p in coin.daily_prices[-30:]]
    relevant.append(coin.price_aud)
    return max(relevant)


def apply_risk_gates(
    signal: SignalResult,
    coin: UniverseCoin,
    metrics: CoinMetrics,
    classification: Classification,
    holding: Optional[Holding],
    previous_tier: Optional[str],
    current_weight_pct: float,
    speculative_pct: float,
    core_pct: float,
    cash_available_aud: float,
    total_value_aud: float,
    config: dict,
) -> FinalAction:
    rcfg = config["risk"]
    held = holding is not None
    action = signal.action
    reasons = list(signal.reasons)

    # --- Fundamentals-broke sell triggers (override everything else) ---
    forced_sell = False
    if held:
        if previous_tier and _TIER_RANK.get(classification.tier, 0) < _TIER_RANK.get(previous_tier, 0):
            forced_sell = True
            reasons.append(f"fundamentals-broke: classification downgraded from {previous_tier} to {classification.tier}")
        if metrics.unlock_risk_flag:
            forced_sell = True
            reasons.append(f"fundamentals-broke: large token unlock (>= {rcfg['large_unlock_flag_pct_of_supply']}% of supply) flagged within 30 days")

    stop_price = None
    if held:
        rolling_high = rolling_high_since(coin, holding.purchase_date)
        if rolling_high:
            stop_price = round(rolling_high * (1 - rcfg["trailing_stop_pct"] / 100), 8)
            if coin.price_aud is not None and coin.price_aud <= stop_price:
                forced_sell = True
                reasons.append(
                    f"trailing stop hit: price A${coin.price_aud:,.4f} <= stop A${stop_price:,.4f} "
                    f"({rcfg['trailing_stop_pct']}% below rolling high A${rolling_high:,.4f})"
                )

    if forced_sell:
        action = SELL

    # --- BUY/ADD eligibility gate: only core / revenue-generating ---
    if action in (BUY, ADD) and classification.tier == SPECULATIVE:
        action = HOLD if held else WATCH
        reasons.append(f"risk gate: only core/revenue-generating coins are eligible for BUY/ADD; "
                        f"{coin.coin_id} is classified speculative -- downgraded to {action}")

    # --- Position size cap ---
    if held and action != SELL:
        if current_weight_pct > rcfg["max_position_pct_per_coin"]:
            action = TRIM
            reasons.append(f"position weight {current_weight_pct:.1f}% exceeds cap "
                            f"{rcfg['max_position_pct_per_coin']}% -- trim to cap")
        elif action == ADD and current_weight_pct >= rcfg["max_position_pct_per_coin"]:
            action = HOLD
            reasons.append(f"position weight {current_weight_pct:.1f}% already at cap -- no further ADD")

    # --- Speculative allocation cap ---
    if action in (BUY, ADD) and classification.tier == SPECULATIVE and speculative_pct >= rcfg["max_total_speculative_allocation_pct"]:
        action = HOLD if held else WATCH
        reasons.append(f"risk gate: speculative allocation {speculative_pct:.1f}% already at/above cap "
                        f"{rcfg['max_total_speculative_allocation_pct']}% -- downgraded to {action}")

    if action == BUY and core_pct < rcfg["min_core_allocation_pct"] and classification.tier == CORE:
        reasons.append(f"portfolio core allocation {core_pct:.1f}% is below the {rcfg['min_core_allocation_pct']}% "
                        f"minimum -- this core coin is a priority BUY to rebuild it")

    # --- Sizing ---
    suggested_aud = None
    suggested_units = None
    if action in (BUY, ADD):
        headroom_pct = max(0.0, rcfg["max_position_pct_per_coin"] - current_weight_pct)
        headroom_aud = headroom_pct / 100 * total_value_aud if total_value_aud else 0.0
        suggested_aud = round(min(cash_available_aud, headroom_aud), 2)
        if suggested_aud <= 0:
            action = HOLD if held else WATCH
            reasons.append("no available cash or position headroom -- downgraded from buy/add signal")
        elif coin.price_aud:
            suggested_units = round(suggested_aud / coin.price_aud, 8)
    elif action == TRIM and held:
        excess_pct = max(0.0, current_weight_pct - rcfg["max_position_pct_per_coin"])
        suggested_units = round(holding.units * (excess_pct / current_weight_pct), 8) if current_weight_pct else None
        if suggested_units:
            suggested_aud = round(suggested_units * coin.price_aud, 2) if coin.price_aud else None
    elif action == SELL and held:
        suggested_units = holding.units
        suggested_aud = round(holding.units * coin.price_aud, 2) if coin.price_aud else None

    tax_context = None
    if held and action in (SELL, TRIM):
        tax_context = compute_tax_context(holding.cost_base_aud, holding.units, coin.price_aud, holding.purchase_date, config)
        if tax_context.within_discount_warning_window:
            reasons.append(f"within {config['au_tax']['cgt_discount_warning_window_days']} days of the 12-month CGT "
                            f"discount date ({tax_context.cgt_discount_date}) -- consider timing")
        reasons.append(f"unrealised {'gain' if tax_context.unrealised_gain_aud >= 0 else 'loss'} "
                        f"A${abs(tax_context.unrealised_gain_aud):,.2f} ({tax_context.unrealised_gain_pct:+.1f}%)")
        reasons.append(SWAP_NOTE)
        if holding.exchange:
            net = net_trade_amount_aud(suggested_aud or 0.0, holding.exchange, config)
            reasons.append(f"net of estimated {holding.exchange} fees/spread: A${net:,.2f} (gross A${suggested_aud or 0:,.2f})")

    return FinalAction(
        coin_id=coin.coin_id,
        action=action,
        original_signal_action=signal.action,
        confidence=signal.confidence,
        score=signal.score,
        held=held,
        suggested_aud=suggested_aud,
        suggested_units=suggested_units,
        entry_price_aud=coin.price_aud,
        stop_price_aud=stop_price,
        reasons=reasons,
        tax_context=tax_context,
        tax_disclaimer=DISCLAIMER if tax_context else None,
    )
