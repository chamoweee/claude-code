import pytest

from tradesys.backtest.portfolio import Portfolio


def test_buy_reduces_cash_and_opens_position():
    p = Portfolio(cash=1000.0)
    p.buy("2024-01-01", "BHP", price=40.0, qty=10, cost=10.0)

    assert p.cash == 1000.0 - (400.0 + 10.0)
    assert p.positions["BHP"].qty == 10
    assert p.positions["BHP"].avg_cost == 40.0


def test_buy_twice_updates_weighted_avg_cost():
    p = Portfolio(cash=10_000.0)
    p.buy("2024-01-01", "BHP", price=40.0, qty=10, cost=0.0)
    p.buy("2024-01-02", "BHP", price=50.0, qty=10, cost=0.0)

    assert p.positions["BHP"].qty == 20
    assert p.positions["BHP"].avg_cost == 45.0


def test_sell_computes_realized_pnl_net_of_cost():
    p = Portfolio(cash=10_000.0)
    p.buy("2024-01-01", "BHP", price=40.0, qty=10, cost=0.0)
    realized = p.sell("2024-01-02", "BHP", price=45.0, qty=10, cost=5.0)

    # proceeds = 450 - 5 = 445; cost basis = 400; pnl = 45
    assert realized == 45.0
    assert "BHP" not in p.positions


def test_sell_more_than_held_raises():
    p = Portfolio(cash=10_000.0)
    p.buy("2024-01-01", "BHP", price=40.0, qty=5, cost=0.0)
    with pytest.raises(ValueError):
        p.sell("2024-01-02", "BHP", price=45.0, qty=10, cost=0.0)


def test_buy_beyond_cash_raises():
    p = Portfolio(cash=100.0)
    with pytest.raises(ValueError):
        p.buy("2024-01-01", "BHP", price=40.0, qty=10, cost=0.0)


def test_mark_to_market_uses_current_price():
    p = Portfolio(cash=1000.0)
    p.buy("2024-01-01", "BHP", price=40.0, qty=10, cost=0.0)
    equity = p.mark_to_market("2024-01-02", {"BHP": 42.0})

    assert equity == (1000.0 - 400.0) + 42.0 * 10
    assert p.equity_curve[-1] == {"date": "2024-01-02", "equity": equity}
