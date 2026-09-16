from tradesys.backtest.costs import trade_cost
from tradesys.config import COSTS


def test_small_trade_hits_minimum_brokerage():
    result = trade_cost(100.0)
    assert result["brokerage"] == COSTS.min_brokerage_aud


def test_large_trade_uses_percentage_brokerage():
    notional = 100_000.0
    result = trade_cost(notional)
    expected_brokerage = notional * COSTS.brokerage_pct_of_notional
    assert expected_brokerage > COSTS.min_brokerage_aud
    assert result["brokerage"] == expected_brokerage


def test_foreign_trade_adds_fx_cost():
    notional = 1000.0
    domestic = trade_cost(notional, is_foreign=False)
    foreign = trade_cost(notional, is_foreign=True)
    assert foreign["fx"] == notional * COSTS.fx_cost_pct
    assert domestic["fx"] == 0.0
    assert foreign["total"] > domestic["total"]


def test_total_is_sum_of_components():
    result = trade_cost(5000.0)
    assert abs(result["total"] - (result["brokerage"] + result["spread"] + result["slippage"] + result["fx"])) < 1e-9
