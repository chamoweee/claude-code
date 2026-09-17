from __future__ import annotations

from crypto_advisor.classify import CORE, REVENUE_GENERATING, SPECULATIVE, classify_coin

from .conftest import make_coin, make_metrics


def test_classifies_core_when_all_thresholds_met(config):
    coin = make_coin(market_cap=20_000_000_000, history_days=1600, listed_exchanges=["Binance", "Kraken", "Coinbase Exchange"])
    metrics = make_metrics(avg_volume_30d_aud=200_000_000)
    result = classify_coin(coin, metrics, config)
    assert result.tier == CORE
    assert any("market cap" in r for r in result.reasons)


def test_not_core_if_one_threshold_missed(config):
    # market cap fine, but too little history and only 1 exchange
    coin = make_coin(market_cap=20_000_000_000, history_days=400, listed_exchanges=["Binance"])
    metrics = make_metrics(avg_volume_30d_aud=200_000_000)
    result = classify_coin(coin, metrics, config)
    assert result.tier != CORE


def test_classifies_revenue_generating(config):
    coin = make_coin(market_cap=2_000_000_000, history_days=800, listed_exchanges=["Kraken"])
    metrics = make_metrics(avg_volume_30d_aud=15_000_000, revenue_quarters_present=7, annual_supply_inflation_pct=2.0)
    result = classify_coin(coin, metrics, config)
    assert result.tier == REVENUE_GENERATING


def test_revenue_generating_needs_low_inflation(config):
    coin = make_coin(market_cap=2_000_000_000, history_days=800, listed_exchanges=["Kraken"])
    metrics = make_metrics(avg_volume_30d_aud=15_000_000, revenue_quarters_present=7, annual_supply_inflation_pct=15.0)
    result = classify_coin(coin, metrics, config)
    assert result.tier == SPECULATIVE


def test_revenue_generating_needs_enough_quarters(config):
    coin = make_coin(market_cap=2_000_000_000, history_days=800, listed_exchanges=["Kraken"])
    metrics = make_metrics(avg_volume_30d_aud=15_000_000, revenue_quarters_present=3, annual_supply_inflation_pct=1.0)
    result = classify_coin(coin, metrics, config)
    assert result.tier == SPECULATIVE


def test_speculative_when_no_revenue_data_available(config):
    coin = make_coin(market_cap=800_000_000, history_days=800, listed_exchanges=["Kraken"])
    metrics = make_metrics(avg_volume_30d_aud=12_000_000, revenue_quarters_present=None, annual_supply_inflation_pct=None)
    result = classify_coin(coin, metrics, config)
    assert result.tier == SPECULATIVE
    assert any("unavailable" in r for r in result.reasons)
