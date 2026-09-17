"""Classifies each universe coin as core / revenue-generating / speculative.
Rules are applied in that order (first match wins) and every decision is
returned with the specific numbers that triggered it, for citation in
reports and advisory reasons.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .metrics import CoinMetrics
from .universe import UniverseCoin

CORE = "core"
REVENUE_GENERATING = "revenue-generating"
SPECULATIVE = "speculative"


@dataclass
class Classification:
    coin_id: str
    tier: str
    reasons: list[str] = field(default_factory=list)


def classify_coin(coin: UniverseCoin, metrics: CoinMetrics, config: dict) -> Classification:
    ccfg = config["classification"]
    core_cfg = ccfg["core"]
    rev_cfg = ccfg["revenue_generating"]

    avg_volume = metrics.avg_volume_30d_aud or 0
    history_days = coin.price_history_days or 0
    exchange_count = len(coin.listed_exchanges)

    core_checks = {
        "market_cap": coin.market_cap_aud >= core_cfg["min_market_cap_aud"],
        "avg_volume_30d": avg_volume >= core_cfg["min_avg_daily_volume_aud_30d"],
        "price_history_days": history_days >= core_cfg["min_price_history_days"],
        "exchange_count": exchange_count >= core_cfg["min_major_exchanges_listed"],
    }
    if all(core_checks.values()):
        return Classification(
            coin_id=coin.coin_id,
            tier=CORE,
            reasons=[
                f"market cap A${coin.market_cap_aud:,.0f} >= A${core_cfg['min_market_cap_aud']:,.0f}",
                f"30d avg volume A${avg_volume:,.0f} >= A${core_cfg['min_avg_daily_volume_aud_30d']:,.0f}",
                f"price history {history_days}d >= {core_cfg['min_price_history_days']}d",
                f"listed on {exchange_count} major exchanges (>= {core_cfg['min_major_exchanges_listed']})",
            ],
        )

    quarters = metrics.revenue_quarters_present
    inflation = metrics.annual_supply_inflation_pct
    revenue_ok = quarters is not None and quarters >= rev_cfg["min_quarters_with_revenue"]
    inflation_ok = inflation is not None and inflation <= rev_cfg["max_annual_supply_inflation_pct"]
    if revenue_ok and inflation_ok:
        return Classification(
            coin_id=coin.coin_id,
            tier=REVENUE_GENERATING,
            reasons=[
                f"revenue present in {quarters}/8 trailing quarters (>= {rev_cfg['min_quarters_with_revenue']})",
                f"annual supply inflation {inflation:.2f}% <= {rev_cfg['max_annual_supply_inflation_pct']}%",
            ],
        )

    reasons = ["did not meet core thresholds: " + ", ".join(k for k, v in core_checks.items() if not v)]
    if quarters is None:
        reasons.append("revenue-quarter data unavailable")
    elif not revenue_ok:
        reasons.append(f"revenue present in only {quarters}/8 trailing quarters (need {rev_cfg['min_quarters_with_revenue']})")
    if inflation is None:
        reasons.append("annual supply inflation unavailable")
    elif not inflation_ok:
        reasons.append(f"annual supply inflation {inflation:.2f}% exceeds {rev_cfg['max_annual_supply_inflation_pct']}%")

    return Classification(coin_id=coin.coin_id, tier=SPECULATIVE, reasons=reasons)
