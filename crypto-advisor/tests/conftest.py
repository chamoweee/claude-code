from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from crypto_advisor.classify import Classification
from crypto_advisor.metrics import CoinMetrics
from crypto_advisor.universe import UniverseCoin


@pytest.fixture
def config() -> dict:
    return {
        "general": {
            "vs_currency": "aud", "secondary_currency": "usd", "refresh_interval_seconds": 300,
            "timezone": "Australia/Sydney", "us_session_close_timezone": "America/New_York",
            "us_session_close_hour": 16, "digest_hour_sydney": 8, "request_timeout_seconds": 20,
        },
        "universe": {
            "min_market_cap_aud": 500_000_000, "min_avg_daily_volume_aud_30d": 10_000_000,
            "min_price_history_days": 730, "max_coins_scanned": 300,
            "major_exchanges": ["Binance", "Coinbase Exchange", "Kraken"],
            "excluded_categories": ["stablecoins", "wrapped-tokens", "liquid-staking-tokens"],
            "excluded_symbol_denylist": ["usdt", "usdc", "wbtc"],
        },
        "classification": {
            "core": {"min_market_cap_aud": 10_000_000_000, "min_avg_daily_volume_aud_30d": 100_000_000,
                      "min_price_history_days": 1500, "min_major_exchanges_listed": 3},
            "revenue_generating": {"min_quarters_with_revenue": 6, "max_annual_supply_inflation_pct": 5.0},
        },
        "movers": {
            "min_liquidity_market_cap_aud": 500_000_000, "min_liquidity_avg_volume_aud_30d": 10_000_000,
            "top_n": 10, "volume_spike_multiple": 3.0,
        },
        "simple_report": {"mover_threshold_pct": 20.0, "top_n": 3},
        "insights": {
            "top_n_shown_first": 5, "near_ath_pct": 5.0, "btc_residual_threshold_pct": 15.0,
            "regime_dominance_shift_pct": 2.0, "sector_rotation_min_spread_pct": 8.0,
        },
        "liquidity_risk": {"max_single_exchange_volume_share_pct": 60.0},
        "signals": {
            "weight_fundamentals": 0.30, "weight_valuation": 0.25, "weight_trend": 0.30, "weight_regime": 0.15,
            "buy_score_threshold": 0.70, "add_score_threshold": 0.55, "trim_score_threshold": 0.35,
            "sell_score_threshold": 0.20,
        },
        "risk": {
            "max_position_pct_per_coin": 15.0, "max_total_speculative_allocation_pct": 20.0,
            "min_core_allocation_pct": 50.0, "trailing_stop_pct": 25.0,
            "large_unlock_flag_pct_of_supply": 5.0, "min_confidence_data_completeness": 0.6,
        },
        "au_tax": {
            "cgt_discount_days": 365, "cgt_discount_warning_window_days": 60,
            "exchange_fees_bps": {"Kraken": 40, "Binance": 30, "default": 50},
        },
        "alerts": {"holding_move_pct_threshold": 8.0, "cooldown_minutes": 120},
        "backtest": {"start_date": "2017-01-01", "rebalance_days": 30, "benchmark_universe_cap": 30, "top_movers_lookback_days": 1},
        "data_sources": {
            "coingecko_base_url": "https://api.coingecko.com/api/v3",
            "defillama_base_url": "https://api.llama.fi",
            "cache_ttl_seconds": {"markets": 240, "coin_detail": 21600, "tickers": 21600, "categories": 3600,
                                   "global": 300, "market_chart": 21600, "defillama": 43200},
            "defillama_slug_map": {"ethereum": "ethereum", "bitcoin": "bitcoin"},
        },
    }


def make_coin(coin_id="testcoin", symbol="tst", price=100.0, market_cap=1_000_000_000, volume_24h=20_000_000,
              pct_1h=0.0, pct_24h=0.0, pct_7d=0.0, avg_volume_30d=15_000_000, history_days=800,
              listed_exchanges=None, daily_prices=None, daily_volumes=None, ath=None, ath_date=None,
              circulating_supply=1_000_000, total_supply=1_000_000, max_supply=1_000_000) -> UniverseCoin:
    if listed_exchanges is None:
        listed_exchanges = ["Kraken"]
    if daily_prices is None:
        daily_prices = [(i * 86_400_000, price) for i in range(history_days)]
    if daily_volumes is None:
        daily_volumes = [(ts, avg_volume_30d) for ts, _ in daily_prices]
    return UniverseCoin(
        coin_id=coin_id, symbol=symbol, name=coin_id.title(), market_cap_aud=market_cap, price_aud=price,
        volume_24h_aud=volume_24h, price_change_pct_1h=pct_1h, price_change_pct_24h=pct_24h,
        price_change_pct_7d=pct_7d, price_change_pct_30d=0.0, ath_aud=ath or price, ath_date=ath_date,
        circulating_supply=circulating_supply, total_supply=total_supply, max_supply=max_supply,
        avg_volume_30d_aud=avg_volume_30d, price_history_days=history_days, listed_exchanges=listed_exchanges,
        daily_prices=daily_prices, daily_volumes=daily_volumes,
    )


def make_metrics(coin_id="testcoin", **kwargs) -> CoinMetrics:
    m = CoinMetrics(coin_id=coin_id)
    for k, v in kwargs.items():
        setattr(m, k, v)
    return m


def make_classification(coin_id="testcoin", tier="core") -> Classification:
    return Classification(coin_id=coin_id, tier=tier, reasons=["test"])
