from tradesys.risk.sizing import position_size


def test_sizes_by_risk_budget():
    # Equity 2000, risk 1% -> $20 risk budget. Entry 10, stop 9 -> $1/share risk -> 20 shares.
    qty = position_size(equity_aud=2000, entry_price=10.0, stop_price=9.0, cash_available_aud=2000, risk_pct=0.01)
    assert qty == 20


def test_capped_by_available_cash():
    # Risk budget would allow far more shares than cash can buy.
    qty = position_size(equity_aud=100_000, entry_price=100.0, stop_price=99.0, cash_available_aud=250, risk_pct=0.01)
    assert qty == 2  # floor(250/100)


def test_zero_when_stop_not_below_entry():
    qty = position_size(equity_aud=2000, entry_price=10.0, stop_price=10.0, cash_available_aud=2000)
    assert qty == 0


def test_zero_when_entry_price_invalid():
    qty = position_size(equity_aud=2000, entry_price=0, stop_price=-1, cash_available_aud=2000)
    assert qty == 0
