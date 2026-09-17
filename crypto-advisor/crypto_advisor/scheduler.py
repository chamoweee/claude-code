"""Orchestrates one full pipeline pass (fetch -> universe -> metrics ->
classify -> movers -> insights -> signals -> risk -> reports) and the live
loop that repeats it on a schedule, checking alerts/digests each cycle.
"""
from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .alerts import CooldownStore, check_instant_alerts, maybe_send_digests
from .classify import CORE, REVENUE_GENERATING, SPECULATIVE, classify_coin
from .config import Env, PROJECT_ROOT, Portfolio, load_config, load_env, load_portfolio
from .fetch import CcxtOhlcvClient, CoinGeckoClient, DefiLlamaClient
from .insights import generate_insights
from .logutil import get_logger
from .metrics import compute_metrics_for_coin
from .movers import compute_movers
from .report import ReportContext, generate_all_reports, read_previous_actions, read_previous_classifications
from .risk import FinalAction, apply_risk_gates, core_allocation_pct, portfolio_weights, speculative_allocation_pct
from .signals import score_coin
from .stream import PriceStream
from .summary import generate_summary
from .universe import build_universe, fetch_forced_coin

logger = get_logger(__name__)

DATA_DIR = PROJECT_ROOT / "data"
LIVE_HISTORY_DIR = DATA_DIR / "live_history"


def _btc_above_200sma(universe) -> Optional[bool]:
    btc = next((c for c in universe if c.coin_id == "bitcoin"), None)
    if not btc or len(btc.daily_prices) < 200:
        return None
    prices = [p for _, p in btc.daily_prices]
    sma200 = sum(prices[-200:]) / 200
    return prices[-1] > sma200


def _peer_price_to_fees_medians(universe, metrics_by_id, classifications) -> dict[str, float]:
    by_tier: dict[str, list[float]] = {CORE: [], REVENUE_GENERATING: [], SPECULATIVE: []}
    class_by_id = {c.coin_id: c.tier for c in classifications}
    for coin in universe:
        m = metrics_by_id.get(coin.coin_id)
        tier = class_by_id.get(coin.coin_id)
        if m and m.price_to_fees and tier:
            by_tier[tier].append(m.price_to_fees)
    return {tier: statistics.median(values) for tier, values in by_tier.items() if values}


def _dominance_n_days_ago(days: int) -> Optional[float]:
    if not LIVE_HISTORY_DIR.exists():
        return None
    target = datetime.now(timezone.utc) - timedelta(days=days)
    best, best_delta = None, timedelta(hours=18)
    for f in LIVE_HISTORY_DIR.glob("*.json"):
        try:
            snap = json.loads(f.read_text())
            ts = datetime.fromisoformat(snap["timestamp"])
            delta = abs(ts - target)
            if delta < best_delta and snap.get("btc_dominance") is not None:
                best, best_delta = snap["btc_dominance"], delta
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return best


def save_live_history_snapshot(ctx: ReportContext) -> None:
    LIVE_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    gd = ctx.global_data or {}
    snapshot = {
        "timestamp": ctx.fetch_time.isoformat(),
        "btc_dominance": (gd.get("market_cap_percentage") or {}).get("btc"),
        "total_mcap_aud": (gd.get("total_market_cap") or {}).get(ctx.config["general"]["vs_currency"]),
        "top_gainers_24h": [r.symbol for r in ctx.movers.get("24h", {}).get("gainers", [])[:10]],
        "top_losers_24h": [r.symbol for r in ctx.movers.get("24h", {}).get("losers", [])[:10]],
        "top_insights": [i.message for i in ctx.insights[:5]],
    }
    filename = ctx.fetch_time.strftime("%Y%m%dT%H%M%SZ") + ".json"
    (LIVE_HISTORY_DIR / filename).write_text(json.dumps(snapshot, indent=2))


def run_pipeline_once(config: dict, env: Env, portfolio: Portfolio, include_advisory: bool = True,
                       cg: Optional[CoinGeckoClient] = None, defillama: Optional[DefiLlamaClient] = None,
                       stream: Optional[PriceStream] = None) -> ReportContext:
    fetch_time = datetime.now(timezone.utc)
    stale_sources: list[str] = []

    cg = cg or CoinGeckoClient(config, api_key=env.coingecko_api_key)
    defillama = defillama or DefiLlamaClient(config)
    try:
        ccxt_client = CcxtOhlcvClient(env.ccxt_exchange)
    except Exception as exc:  # noqa: BLE001 - ccxt/exchange init issues must not crash the pipeline
        logger.warning("Could not initialise ccxt exchange %s: %s", env.ccxt_exchange, exc)
        ccxt_client = None
        stale_sources.append(f"ccxt:{env.ccxt_exchange}")

    if not cg.ping():
        stale_sources.append("coingecko")
        logger.warning("CoinGecko ping failed -- data may be stale/incomplete this run")

    universe, movers_candidates = build_universe(cg, config)

    holding_ids = portfolio.holding_ids()
    watchlist_ids = set(portfolio.watchlist)
    universe_ids = {c.coin_id for c in universe}
    missing_holdings = (holding_ids | watchlist_ids) - universe_ids
    forced_delisted: list[str] = []
    for coin_id in missing_holdings:
        forced = fetch_forced_coin(cg, coin_id, config["general"]["vs_currency"], config["universe"]["major_exchanges"])
        if forced is None:
            forced_delisted.append(coin_id)
        else:
            universe.append(forced)

    usd_to_aud = cg.usd_to_aud_rate()
    if usd_to_aud is None:
        stale_sources.append("coingecko:exchange_rates")

    btc = next((c for c in universe if c.coin_id == "bitcoin"), None)
    btc_prices = [p for _, p in btc.daily_prices] if btc else []

    metrics_by_id = {}
    for coin in universe:
        metrics_by_id[coin.coin_id] = compute_metrics_for_coin(coin, btc_prices, cg, defillama, config, usd_to_aud, ccxt_client)

    classifications = [classify_coin(coin, metrics_by_id[coin.coin_id], config) for coin in universe]

    global_data = cg.global_data()
    if global_data is None:
        stale_sources.append("coingecko:global")
    categories = cg.categories()
    if not categories:
        stale_sources.append("coingecko:categories")

    movers = compute_movers(movers_candidates, universe, classifications, holding_ids, config)

    dominance_7d_ago = _dominance_n_days_ago(7)
    insights = generate_insights(universe, metrics_by_id, categories, global_data, dominance_7d_ago,
                                  holding_ids, watchlist_ids, config)

    final_actions = []
    weights_by_id: dict[str, float] = {}
    total_value = 0.0
    core_pct = speculative_pct = 0.0
    if include_advisory:
        prices_by_id = {c.coin_id: c.price_aud for c in universe if c.price_aud is not None}
        weights_by_id, total_value = portfolio_weights(portfolio.holdings, prices_by_id, portfolio.cash_aud)
        class_by_id = {c.coin_id: c for c in classifications}
        speculative_pct = speculative_allocation_pct(portfolio.holdings, prices_by_id, class_by_id, total_value)
        core_pct = core_allocation_pct(portfolio.holdings, prices_by_id, class_by_id, total_value)
        peer_medians = _peer_price_to_fees_medians(universe, metrics_by_id, classifications)
        btc_regime = _btc_above_200sma(universe)
        previous_tiers = read_previous_classifications()
        holdings_by_id = {h.coin_id: h for h in portfolio.holdings}

        eval_ids = universe_ids | holding_ids | watchlist_ids
        for coin_id in eval_ids:
            coin = next((c for c in universe if c.coin_id == coin_id), None)
            holding = holdings_by_id.get(coin_id)
            if coin is None:
                if holding is not None:
                    final_actions.append(_delisted_sell_action(coin_id, holding))
                continue
            metrics = metrics_by_id[coin_id]
            classification = next(c for c in classifications if c.coin_id == coin_id)
            signal = score_coin(coin, metrics, classification, holding is not None, btc_regime,
                                 peer_medians.get(classification.tier), config)
            final = apply_risk_gates(
                signal, coin, metrics, classification, holding, previous_tiers.get(coin_id),
                weights_by_id.get(coin_id, 0.0), speculative_pct, core_pct, portfolio.cash_aud, total_value, config,
            )
            final_actions.append(final)

    ws_prices: dict[str, tuple[float, bool]] = {}
    if stream is not None:
        interesting_ids = holding_ids | watchlist_ids
        for coin in universe:
            if coin.coin_id not in interesting_ids:
                continue
            ws_symbol = f"{coin.symbol}usdt"
            price = stream.get_price(ws_symbol)
            if price is not None:
                ws_prices[coin.coin_id] = (price, stream.is_stale(ws_symbol))

    summary_text = None
    ctx = ReportContext(
        universe=universe, metrics_by_id=metrics_by_id, classifications=classifications, movers=movers,
        insights=insights, global_data=global_data, categories=categories, final_actions=final_actions,
        portfolio=portfolio, summary_text=summary_text, fetch_time=fetch_time, stale_sources=stale_sources,
        config=config, weights_by_id=weights_by_id, total_value_aud=total_value, core_pct=core_pct,
        speculative_pct=speculative_pct, ws_prices=ws_prices,
    )

    if env.anthropic_api_key:
        report_data = {
            "overview": {"stale_sources": stale_sources},
            "insights": [i.message for i in insights[:10]],
            "top_actions": [{"coin": a.coin_id, "action": a.action, "confidence": a.confidence} for a in final_actions],
        }
        ctx.summary_text = generate_summary(report_data, env.anthropic_api_key)

    return ctx


def _delisted_sell_action(coin_id: str, holding) -> FinalAction:
    return FinalAction(
        coin_id=coin_id, action="SELL", original_signal_action="SELL", confidence="low", score=0.0, held=True,
        suggested_units=holding.units, suggested_aud=None, entry_price_aud=None, stop_price_aud=None,
        reasons=[f"{coin_id} no longer returns market data from CoinGecko -- possible delisting. "
                 f"Confidence is low because this could also be a temporary data outage; verify manually before acting."],
    )


def run_once_and_report(config: dict, env: Env, portfolio: Portfolio, include_advisory: bool = True,
                         stream: Optional[PriceStream] = None) -> ReportContext:
    ctx = run_pipeline_once(config, env, portfolio, include_advisory=include_advisory, stream=stream)
    generate_all_reports(ctx)
    save_live_history_snapshot(ctx)
    return ctx


def _start_price_stream(ctx: ReportContext, portfolio: Portfolio, config: dict) -> Optional[PriceStream]:
    """Best-effort: subscribes to Binance's public ticker stream for held/
    watchlisted coins once we know their symbols from the first cycle. Never
    blocks or fails the live loop -- purely a supplementary near-real-time
    price shown alongside the per-cycle REST price (see ReportContext.ws_prices)."""
    interesting_ids = portfolio.holding_ids() | set(portfolio.watchlist)
    symbols = sorted({f"{c.symbol}usdt" for c in ctx.universe if c.coin_id in interesting_ids})
    if not symbols:
        return None
    try:
        stream = PriceStream(symbols, base_ws_url=config["data_sources"]["binance_ws_base_url"])
        stream.start()
        logger.info("Started Binance WS price stream for %s", symbols)
        return stream
    except Exception as exc:  # noqa: BLE001 - live stream is a nice-to-have, never fatal
        logger.warning("Could not start Binance WS stream (REST prices still used for everything): %s", exc)
        return None


def run_live_loop(config: dict, env: Env, portfolio: Portfolio, max_iterations: Optional[int] = None) -> None:
    interval = config["general"]["refresh_interval_seconds"]
    store = CooldownStore.load()
    stream: Optional[PriceStream] = None
    iterations = 0
    try:
        while max_iterations is None or iterations < max_iterations:
            try:
                previous = read_previous_actions()
                ctx = run_once_and_report(config, env, portfolio, include_advisory=True, stream=stream)
                if stream is None:
                    stream = _start_price_stream(ctx, portfolio, config)
                check_instant_alerts(ctx, previous, env, config, store)
                maybe_send_digests(ctx, env, config)
                logger.info("Live cycle complete at %s (stale: %s)", ctx.fetch_time.isoformat(), ctx.stale_sources or "none")
            except Exception as exc:  # noqa: BLE001 - one bad cycle should never kill the live loop
                logger.error("Live cycle failed: %s", exc, exc_info=True)
            iterations += 1
            if max_iterations is None or iterations < max_iterations:
                time.sleep(interval)
    finally:
        if stream is not None:
            stream.stop()
