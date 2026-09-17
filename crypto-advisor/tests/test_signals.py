from __future__ import annotations

from crypto_advisor.signals import (
    ADD,
    BUY,
    HOLD,
    SELL,
    TRIM,
    WATCH,
    _action_from_score,
    fundamentals_score,
    regime_score,
    score_coin,
    trend_score,
)

from .conftest import make_classification, make_coin, make_metrics


def test_top_mover_status_never_affects_score(config):
    """Regression test for the risk rule: 'top-mover status alone never
    triggers BUY; chasing short-term pumps is not a signal.'"""
    metrics = make_metrics(sma_50=90.0, sma_200=80.0, price_to_fees=10.0, annual_supply_inflation_pct=2.0,
                            revenue_quarters_present=7, pct_below_ath=-5.0)
    cls = make_classification(tier="core")

    calm_coin = make_coin(price=100.0, pct_1h=0.1, pct_24h=0.5, pct_7d=1.0)
    mooning_coin = make_coin(price=100.0, pct_1h=15.0, pct_24h=80.0, pct_7d=200.0)

    calm_result = score_coin(calm_coin, metrics, cls, held=False, btc_above_200sma=True,
                              peer_price_to_fees_median=10.0, config=config)
    mooning_result = score_coin(mooning_coin, metrics, cls, held=False, btc_above_200sma=True,
                                 peer_price_to_fees_median=10.0, config=config)

    assert calm_result.score == mooning_result.score
    assert calm_result.component_scores == mooning_result.component_scores
    assert calm_result.action == mooning_result.action


def test_fundamentals_score_ranks_core_above_revenue_above_speculative(config):
    metrics = make_metrics()
    core_score, _ = fundamentals_score(make_classification(tier="core"), metrics, config)
    rev_score, _ = fundamentals_score(make_classification(tier="revenue-generating"), metrics, config)
    spec_score, _ = fundamentals_score(make_classification(tier="speculative"), metrics, config)
    assert core_score > rev_score > spec_score


def test_fundamentals_score_penalised_by_inflation_and_unlock_risk(config):
    cls = make_classification(tier="core")
    base, _ = fundamentals_score(cls, make_metrics(annual_supply_inflation_pct=0.0), config)
    inflated, _ = fundamentals_score(cls, make_metrics(annual_supply_inflation_pct=20.0), config)
    unlock_risk, _ = fundamentals_score(cls, make_metrics(annual_supply_inflation_pct=0.0, unlock_risk_flag=True), config)
    assert inflated < base
    assert unlock_risk < base


def test_trend_score_rewards_price_above_moving_averages():
    coin = make_coin(price=110.0)
    above_both, _ = trend_score(coin, make_metrics(sma_50=100.0, sma_200=90.0))
    below_both, _ = trend_score(coin, make_metrics(sma_50=120.0, sma_200=130.0))
    assert above_both > below_both
    assert above_both == 1.0  # +0.4 +0.4 +0.2 golden-cross bonus (sma50>sma200)


def test_regime_score_bullish_beats_bearish():
    bullish, _ = regime_score(True)
    bearish, _ = regime_score(False)
    unknown, _ = regime_score(None)
    assert bullish > unknown > bearish


def test_action_from_score_thresholds(config):
    scfg = config["signals"]
    assert _action_from_score(scfg["buy_score_threshold"], held=False, config=config) == BUY
    assert _action_from_score(scfg["buy_score_threshold"], held=True, config=config) == ADD
    assert _action_from_score(scfg["add_score_threshold"], held=True, config=config) == ADD
    assert _action_from_score(scfg["add_score_threshold"], held=False, config=config) == WATCH
    assert _action_from_score(scfg["trim_score_threshold"], held=True, config=config) == HOLD
    assert _action_from_score(scfg["sell_score_threshold"], held=True, config=config) == TRIM
    assert _action_from_score(0.0, held=True, config=config) == SELL
    assert _action_from_score(0.0, held=False, config=config) == WATCH
