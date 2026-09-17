"""Top gainers/losers tables for 1h/24h/7d, split into a main (liquid) table
and a "high-risk movers" table for thin coins below the liquidity filter --
so pump-and-dump micro caps don't dominate the headline tables.
"""
from __future__ import annotations

from dataclasses import dataclass

from .classify import Classification
from .universe import UniverseCoin

TIMEFRAMES = {
    "1h": "price_change_percentage_1h_in_currency",
    "24h": "price_change_percentage_24h_in_currency",
    "7d": "price_change_percentage_7d_in_currency",
}


@dataclass
class MoverRow:
    coin_id: str
    symbol: str
    name: str
    price_aud: float
    pct_change: float
    volume_24h_aud: float | None
    volume_vs_30d_avg: float | None
    market_cap_aud: float | None
    classification: str
    held: bool


def _liquidity_pass(row: dict, config: dict) -> bool:
    mcfg = config["movers"]
    market_cap = row.get("market_cap") or 0
    volume_24h = row.get("total_volume") or 0
    return market_cap >= mcfg["min_liquidity_market_cap_aud"] and volume_24h >= mcfg["min_liquidity_avg_volume_aud_30d"]


def _build_row(
    row: dict,
    pct_change: float,
    universe_by_id: dict[str, UniverseCoin],
    classification_by_id: dict[str, Classification],
    holding_ids: set[str],
) -> MoverRow:
    coin_id = row["id"]
    universe_coin = universe_by_id.get(coin_id)
    classification = classification_by_id.get(coin_id)
    volume_24h = row.get("total_volume")
    volume_vs_30d = None
    if universe_coin and universe_coin.avg_volume_30d_aud:
        volume_vs_30d = (volume_24h / universe_coin.avg_volume_30d_aud) if volume_24h else None
    return MoverRow(
        coin_id=coin_id,
        symbol=(row.get("symbol") or "").upper(),
        name=row.get("name", coin_id),
        price_aud=row.get("current_price"),
        pct_change=pct_change,
        volume_24h_aud=volume_24h,
        volume_vs_30d_avg=volume_vs_30d,
        market_cap_aud=row.get("market_cap"),
        classification=classification.tier if classification else "not in universe",
        held=coin_id in holding_ids,
    )


def compute_movers(
    candidates: list[dict],
    universe: list[UniverseCoin],
    classifications: list[Classification],
    holding_ids: set[str],
    config: dict,
) -> dict[str, dict[str, list[MoverRow]]]:
    universe_by_id = {c.coin_id: c for c in universe}
    classification_by_id = {c.coin_id: c for c in classifications}
    top_n = config["movers"]["top_n"]

    result: dict[str, dict[str, list[MoverRow]]] = {}
    for label, field in TIMEFRAMES.items():
        liquid_rows, thin_rows = [], []
        for row in candidates:
            pct = row.get(field)
            if pct is None:
                continue
            mover_row = _build_row(row, pct, universe_by_id, classification_by_id, holding_ids)
            (liquid_rows if _liquidity_pass(row, config) else thin_rows).append(mover_row)

        liquid_rows.sort(key=lambda r: r.pct_change, reverse=True)
        thin_rows.sort(key=lambda r: r.pct_change, reverse=True)

        result[label] = {
            "gainers": liquid_rows[:top_n],
            "losers": list(reversed(liquid_rows[-top_n:])) if liquid_rows else [],
            "high_risk_gainers": thin_rows[:top_n],
            "high_risk_losers": list(reversed(thin_rows[-top_n:])) if thin_rows else [],
        }
    return result
