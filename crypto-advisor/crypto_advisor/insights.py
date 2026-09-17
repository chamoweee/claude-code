"""Rules-based insight engine. Every insight cites the specific numbers that
triggered it and carries an importance score so the top N can be shown
first. No insight is generated from a rule whose inputs are missing --
missing data means the rule is skipped for that coin, not guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .classify import Classification
from .logutil import get_logger
from .metrics import CoinMetrics, annualized_volatility_pct, sma
from .universe import UniverseCoin

logger = get_logger(__name__)


@dataclass
class Insight:
    rule: str
    importance: float
    message: str
    coin_id: str | None = None
    numbers: dict = field(default_factory=dict)


def _sma_at(prices: list[float], window: int, offset_from_end: int) -> float | None:
    """SMA of `window` days, ending `offset_from_end` days before the last price
    (0 = today, 1 = yesterday's close), so we can detect a cross without
    look-ahead."""
    end = len(prices) - offset_from_end
    start = end - window
    if start < 0 or end <= 0:
        return None
    return sma(prices[start:end], window)


def volume_spike_insights(universe: list[UniverseCoin], metrics_by_id: dict[str, CoinMetrics], config: dict) -> list[Insight]:
    multiple = config["movers"]["volume_spike_multiple"]
    out = []
    for coin in universe:
        m = metrics_by_id.get(coin.coin_id)
        if not m or not m.avg_volume_30d_aud or not coin.volume_24h_aud:
            continue
        ratio = coin.volume_24h_aud / m.avg_volume_30d_aud
        if ratio >= multiple:
            out.append(Insight(
                rule="volume_spike",
                coin_id=coin.coin_id,
                importance=min(ratio / multiple, 3.0) * 10,
                message=f"{coin.symbol.upper()} 24h volume is {ratio:.1f}x its 30d average "
                        f"(A${coin.volume_24h_aud:,.0f} vs A${m.avg_volume_30d_aud:,.0f})",
                numbers={"volume_24h_aud": coin.volume_24h_aud, "avg_volume_30d_aud": m.avg_volume_30d_aud, "ratio": round(ratio, 2)},
            ))
    return out


def moving_average_cross_insights(universe: list[UniverseCoin], config: dict) -> list[Insight]:
    out = []
    for coin in universe:
        prices = [p for _, p in coin.daily_prices]
        if len(prices) < 201:
            continue
        for window in (50, 200):
            sma_today = _sma_at(prices, window, 0)
            sma_yesterday = _sma_at(prices, window, 1)
            if sma_today is None or sma_yesterday is None:
                continue
            price_today, price_yesterday = prices[-1], prices[-2]
            was_below = price_yesterday < sma_yesterday
            is_above = price_today >= sma_today
            was_above = price_yesterday >= sma_yesterday
            is_below = price_today < sma_today
            if was_below and is_above:
                out.append(Insight(
                    rule=f"sma{window}_cross_up", coin_id=coin.coin_id, importance=15 if window == 200 else 8,
                    message=f"{coin.symbol.upper()} crossed above its {window}-day moving average "
                            f"(price A${price_today:,.4f} vs SMA{window} A${sma_today:,.4f})",
                    numbers={"price": price_today, f"sma{window}": sma_today},
                ))
            elif was_above and is_below:
                out.append(Insight(
                    rule=f"sma{window}_cross_down", coin_id=coin.coin_id, importance=15 if window == 200 else 8,
                    message=f"{coin.symbol.upper()} crossed below its {window}-day moving average "
                            f"(price A${price_today:,.4f} vs SMA{window} A${sma_today:,.4f})",
                    numbers={"price": price_today, f"sma{window}": sma_today},
                ))
    return out


def ath_52w_insights(universe: list[UniverseCoin], metrics_by_id: dict[str, CoinMetrics], config: dict) -> list[Insight]:
    near_pct = config["insights"]["near_ath_pct"]
    out = []
    for coin in universe:
        m = metrics_by_id.get(coin.coin_id)
        if not m:
            continue
        if m.pct_below_ath is not None and abs(m.pct_below_ath) <= near_pct:
            out.append(Insight(
                rule="near_ath", coin_id=coin.coin_id, importance=12,
                message=f"{coin.symbol.upper()} is within {abs(m.pct_below_ath):.1f}% of its all-time high",
                numbers={"pct_below_ath": m.pct_below_ath, "ath_aud": coin.ath_aud, "price_aud": coin.price_aud},
            ))
        if m.week52_high is not None and coin.price_aud is not None and coin.price_aud >= m.week52_high:
            out.append(Insight(
                rule="new_52w_high", coin_id=coin.coin_id, importance=10,
                message=f"{coin.symbol.upper()} hit a new 52-week high of A${coin.price_aud:,.4f}",
                numbers={"price_aud": coin.price_aud, "prior_52w_high": m.week52_high},
            ))
        if m.week52_low is not None and coin.price_aud is not None and coin.price_aud <= m.week52_low:
            out.append(Insight(
                rule="new_52w_low", coin_id=coin.coin_id, importance=10,
                message=f"{coin.symbol.upper()} hit a new 52-week low of A${coin.price_aud:,.4f}",
                numbers={"price_aud": coin.price_aud, "prior_52w_low": m.week52_low},
            ))
    return out


def btc_residual_insights(universe: list[UniverseCoin], metrics_by_id: dict[str, CoinMetrics], btc_24h_change: float | None, config: dict) -> list[Insight]:
    if btc_24h_change is None:
        return []
    threshold = config["insights"]["btc_residual_threshold_pct"]
    out = []
    for coin in universe:
        if coin.coin_id == "bitcoin":
            continue
        m = metrics_by_id.get(coin.coin_id)
        if not m or m.beta_to_btc_2y is None or coin.price_change_pct_24h is None:
            continue
        predicted = m.beta_to_btc_2y * btc_24h_change
        residual = coin.price_change_pct_24h - predicted
        if abs(residual) >= threshold:
            out.append(Insight(
                rule="btc_residual_move", coin_id=coin.coin_id, importance=min(abs(residual) / threshold, 3.0) * 9,
                message=f"{coin.symbol.upper()} moved {coin.price_change_pct_24h:+.1f}% (24h), "
                        f"{residual:+.1f}pp more than its BTC-beta ({m.beta_to_btc_2y:.2f}) would predict "
                        f"given BTC's {btc_24h_change:+.1f}%",
                numbers={"actual_24h_pct": coin.price_change_pct_24h, "predicted_pct": round(predicted, 2),
                         "residual_pct": round(residual, 2), "beta": m.beta_to_btc_2y},
            ))
    return out


def sector_rotation_insights(categories: list[dict], config: dict) -> list[Insight]:
    ranked = [c for c in categories if c.get("market_cap_change_24h") is not None]
    if len(ranked) < 2:
        return []
    ranked.sort(key=lambda c: c["market_cap_change_24h"], reverse=True)
    best, worst = ranked[0], ranked[-1]
    spread = best["market_cap_change_24h"] - worst["market_cap_change_24h"]
    threshold = config["insights"]["sector_rotation_min_spread_pct"]
    if spread < threshold:
        return []
    return [Insight(
        rule="sector_rotation", importance=11,
        message=f"Sector rotation: {best['name']} +{best['market_cap_change_24h']:.1f}% (24h) vs "
                f"{worst['name']} {worst['market_cap_change_24h']:.1f}% -- a {spread:.1f}pp spread",
        numbers={"best_category": best["name"], "best_pct": best["market_cap_change_24h"],
                 "worst_category": worst["name"], "worst_pct": worst["market_cap_change_24h"], "spread": spread},
    )]


def regime_insights(btc_prices: list[float], global_data: dict | None, dominance_7d_ago: float | None, config: dict) -> list[Insight]:
    out = []
    if len(btc_prices) >= 201:
        sma200_today = _sma_at(btc_prices, 200, 0)
        sma200_yesterday = _sma_at(btc_prices, 200, 1)
        if sma200_today is not None and sma200_yesterday is not None:
            price_today, price_yesterday = btc_prices[-1], btc_prices[-2]
            if price_yesterday < sma200_yesterday and price_today >= sma200_today:
                out.append(Insight(rule="btc_regime_change", coin_id="bitcoin", importance=25,
                    message=f"BTC crossed above its 200-day moving average (A${price_today:,.0f} vs SMA200 A${sma200_today:,.0f}) -- regime shift to bullish",
                    numbers={"price": price_today, "sma200": sma200_today}))
            elif price_yesterday >= sma200_yesterday and price_today < sma200_today:
                out.append(Insight(rule="btc_regime_change", coin_id="bitcoin", importance=25,
                    message=f"BTC crossed below its 200-day moving average (A${price_today:,.0f} vs SMA200 A${sma200_today:,.0f}) -- regime shift to bearish",
                    numbers={"price": price_today, "sma200": sma200_today}))
    if global_data and dominance_7d_ago is not None:
        dominance_now = (global_data.get("market_cap_percentage") or {}).get("btc")
        if dominance_now is not None:
            shift = dominance_now - dominance_7d_ago
            if abs(shift) >= config["insights"]["regime_dominance_shift_pct"]:
                direction = "up" if shift > 0 else "down"
                out.append(Insight(rule="dominance_shift", importance=14,
                    message=f"BTC dominance moved {direction} {abs(shift):.1f}pp over 7 days, now {dominance_now:.1f}%",
                    numbers={"dominance_now": dominance_now, "dominance_7d_ago": dominance_7d_ago, "shift": shift}))
    return out


def holdings_watchlist_insights(
    universe_by_id: dict[str, UniverseCoin],
    holding_ids: set[str],
    watchlist_ids: set[str],
    config: dict,
) -> list[Insight]:
    threshold = config["alerts"]["holding_move_pct_threshold"]
    out = []
    for coin_id in holding_ids | watchlist_ids:
        coin = universe_by_id.get(coin_id)
        if not coin or coin.price_change_pct_24h is None:
            continue
        if abs(coin.price_change_pct_24h) >= threshold:
            tag = "holding" if coin_id in holding_ids else "watchlist"
            out.append(Insight(
                rule="holding_big_move", coin_id=coin_id, importance=20,
                message=f"Your {tag} {coin.symbol.upper()} moved {coin.price_change_pct_24h:+.1f}% in 24h "
                        f"(A${coin.price_aud:,.4f})",
                numbers={"pct_change_24h": coin.price_change_pct_24h, "price_aud": coin.price_aud},
            ))
    return out


def generate_insights(
    universe: list[UniverseCoin],
    metrics_by_id: dict[str, CoinMetrics],
    categories: list[dict],
    global_data: dict | None,
    dominance_7d_ago: float | None,
    holding_ids: set[str],
    watchlist_ids: set[str],
    config: dict,
) -> list[Insight]:
    btc = next((c for c in universe if c.coin_id == "bitcoin"), None)
    btc_prices = [p for _, p in btc.daily_prices] if btc else []
    btc_24h_change = btc.price_change_pct_24h if btc else None
    universe_by_id = {c.coin_id: c for c in universe}

    all_insights: list[Insight] = []
    all_insights += volume_spike_insights(universe, metrics_by_id, config)
    all_insights += moving_average_cross_insights(universe, config)
    all_insights += ath_52w_insights(universe, metrics_by_id, config)
    all_insights += btc_residual_insights(universe, metrics_by_id, btc_24h_change, config)
    all_insights += sector_rotation_insights(categories, config)
    all_insights += regime_insights(btc_prices, global_data, dominance_7d_ago, config)
    all_insights += holdings_watchlist_insights(universe_by_id, holding_ids, watchlist_ids, config)

    all_insights.sort(key=lambda i: i.importance, reverse=True)
    return all_insights
