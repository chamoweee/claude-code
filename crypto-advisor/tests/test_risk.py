from __future__ import annotations

from datetime import datetime, timedelta

from crypto_advisor.config import Holding
from crypto_advisor.risk import apply_risk_gates
from crypto_advisor.signals import ADD, BUY, HOLD, SELL, TRIM, WATCH, SignalResult

from .conftest import make_classification, make_coin, make_metrics


def _signal(action, score=0.8):
    return SignalResult(coin_id="testcoin", action=action, score=score, confidence="high",
                         component_scores={}, reasons=["base signal reason"])


def test_speculative_coin_cannot_buy(config):
    coin = make_coin(coin_id="testcoin", price=10.0)
    metrics = make_metrics("testcoin")
    cls = make_classification("testcoin", tier="speculative")
    result = apply_risk_gates(_signal(BUY), coin, metrics, cls, holding=None, previous_tier=None,
                               current_weight_pct=0.0, speculative_pct=0.0, core_pct=50.0,
                               cash_available_aud=1000.0, total_value_aud=10000.0, config=config)
    assert result.action == WATCH
    assert any("only core/revenue-generating" in r for r in result.reasons)


def test_speculative_coin_cannot_add_when_held(config):
    coin = make_coin(coin_id="testcoin", price=10.0)
    metrics = make_metrics("testcoin")
    cls = make_classification("testcoin", tier="speculative")
    holding = Holding(coin_id="testcoin", units=10, cost_base_aud=90.0, purchase_date="2024-01-01")
    result = apply_risk_gates(_signal(ADD), coin, metrics, cls, holding=holding, previous_tier=None,
                               current_weight_pct=5.0, speculative_pct=5.0, core_pct=50.0,
                               cash_available_aud=1000.0, total_value_aud=10000.0, config=config)
    assert result.action == HOLD


def test_core_coin_can_buy(config):
    coin = make_coin(coin_id="testcoin", price=10.0)
    metrics = make_metrics("testcoin")
    cls = make_classification("testcoin", tier="core")
    result = apply_risk_gates(_signal(BUY), coin, metrics, cls, holding=None, previous_tier=None,
                               current_weight_pct=0.0, speculative_pct=0.0, core_pct=20.0,
                               cash_available_aud=1000.0, total_value_aud=10000.0, config=config)
    assert result.action == BUY
    assert result.suggested_aud is not None and result.suggested_aud > 0


def test_position_over_cap_forces_trim(config):
    coin = make_coin(coin_id="testcoin", price=10.0)
    metrics = make_metrics("testcoin")
    cls = make_classification("testcoin", tier="core")
    holding = Holding(coin_id="testcoin", units=200, cost_base_aud=1500.0, purchase_date="2024-01-01")
    # current_weight_pct (20%) exceeds cap (15%) -- even though the signal says ADD
    result = apply_risk_gates(_signal(ADD), coin, metrics, cls, holding=holding, previous_tier=None,
                               current_weight_pct=20.0, speculative_pct=0.0, core_pct=60.0,
                               cash_available_aud=1000.0, total_value_aud=10000.0, config=config)
    assert result.action == TRIM
    assert result.suggested_units is not None and result.suggested_units > 0


def test_trailing_stop_forces_sell(config):
    purchase_date = (datetime.today() - timedelta(days=100)).strftime("%Y-%m-%d")
    # price crashed from a rolling high of 100 down to 70 -- that's a 30% drop, past the 25% trailing stop
    prices = [(i * 86_400_000, 100.0) for i in range(90)] + [(90 * 86_400_000, 70.0)]
    coin = make_coin(coin_id="testcoin", price=70.0, daily_prices=prices)
    metrics = make_metrics("testcoin")
    cls = make_classification("testcoin", tier="core")
    holding = Holding(coin_id="testcoin", units=10, cost_base_aud=900.0, purchase_date=purchase_date)
    result = apply_risk_gates(_signal(HOLD, score=0.5), coin, metrics, cls, holding=holding, previous_tier=None,
                               current_weight_pct=5.0, speculative_pct=0.0, core_pct=60.0,
                               cash_available_aud=1000.0, total_value_aud=10000.0, config=config)
    assert result.action == SELL
    assert any("trailing stop hit" in r for r in result.reasons)


def test_fundamentals_broke_classification_downgrade_forces_sell(config):
    coin = make_coin(coin_id="testcoin", price=10.0)
    metrics = make_metrics("testcoin")
    cls = make_classification("testcoin", tier="speculative")
    holding = Holding(coin_id="testcoin", units=10, cost_base_aud=90.0, purchase_date="2024-01-01")
    result = apply_risk_gates(_signal(HOLD, score=0.5), coin, metrics, cls, holding=holding, previous_tier="core",
                               current_weight_pct=5.0, speculative_pct=0.0, core_pct=60.0,
                               cash_available_aud=1000.0, total_value_aud=10000.0, config=config)
    assert result.action == SELL
    assert any("fundamentals-broke" in r for r in result.reasons)


def test_unlock_risk_flag_forces_sell_when_held(config):
    coin = make_coin(coin_id="testcoin", price=10.0)
    metrics = make_metrics("testcoin", unlock_risk_flag=True)
    cls = make_classification("testcoin", tier="core")
    holding = Holding(coin_id="testcoin", units=10, cost_base_aud=90.0, purchase_date="2024-01-01")
    result = apply_risk_gates(_signal(HOLD, score=0.5), coin, metrics, cls, holding=holding, previous_tier="core",
                               current_weight_pct=5.0, speculative_pct=0.0, core_pct=60.0,
                               cash_available_aud=1000.0, total_value_aud=10000.0, config=config)
    assert result.action == SELL


def test_speculative_allocation_cap_blocks_new_buy(config):
    coin = make_coin(coin_id="testcoin", price=10.0)
    metrics = make_metrics("testcoin")
    cls = make_classification("testcoin", tier="speculative")
    # can't get here via the BUY path since speculative already blocks BUY outright;
    # this test documents that the speculative-cap gate is a no-op once the tier gate
    # has already downgraded the action (defense in depth, not double-counted).
    result = apply_risk_gates(_signal(BUY), coin, metrics, cls, holding=None, previous_tier=None,
                               current_weight_pct=0.0, speculative_pct=25.0, core_pct=50.0,
                               cash_available_aud=1000.0, total_value_aud=10000.0, config=config)
    assert result.action == WATCH


def test_buy_sizing_limited_by_available_cash(config):
    coin = make_coin(coin_id="testcoin", price=10.0)
    metrics = make_metrics("testcoin")
    cls = make_classification("testcoin", tier="core")
    result = apply_risk_gates(_signal(BUY), coin, metrics, cls, holding=None, previous_tier=None,
                               current_weight_pct=0.0, speculative_pct=0.0, core_pct=20.0,
                               cash_available_aud=50.0, total_value_aud=10000.0, config=config)
    # headroom would be 15% of 10000 = 1500, but only $50 cash available
    assert result.suggested_aud == 50.0


def test_tax_context_attached_on_sell_for_held_coin(config):
    coin = make_coin(coin_id="testcoin", price=20.0)
    metrics = make_metrics("testcoin")
    cls = make_classification("testcoin", tier="core")
    holding = Holding(coin_id="testcoin", units=10, cost_base_aud=100.0, purchase_date="2024-01-01", exchange="Kraken")
    result = apply_risk_gates(_signal(SELL, score=0.1), coin, metrics, cls, holding=holding, previous_tier="core",
                               current_weight_pct=5.0, speculative_pct=0.0, core_pct=60.0,
                               cash_available_aud=1000.0, total_value_aud=10000.0, config=config)
    assert result.tax_context is not None
    assert result.tax_context.unrealised_gain_aud == 100.0  # 10 units * $20 - $100 cost base
    assert result.tax_disclaimer is not None
