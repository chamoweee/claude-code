from __future__ import annotations

from crypto_advisor.movers import compute_movers

from .conftest import make_classification, make_coin


def _row(coin_id, pct_24h, market_cap=1_000_000_000, volume=20_000_000, price=10.0):
    return {
        "id": coin_id, "symbol": coin_id[:4], "name": coin_id, "current_price": price,
        "market_cap": market_cap, "total_volume": volume,
        "price_change_percentage_1h_in_currency": pct_24h / 24,
        "price_change_percentage_24h_in_currency": pct_24h,
        "price_change_percentage_7d_in_currency": pct_24h * 3,
    }


def test_gainers_sorted_descending(config):
    candidates = [_row("a", 5.0), _row("b", 20.0), _row("c", -3.0)]
    result = compute_movers(candidates, [], [], set(), config)
    gainers = result["24h"]["gainers"]
    assert [g.coin_id for g in gainers] == ["b", "a", "c"]


def test_losers_sorted_ascending_worst_first(config):
    candidates = [_row("a", 5.0), _row("b", -20.0), _row("c", -3.0)]
    result = compute_movers(candidates, [], [], set(), config)
    losers = result["24h"]["losers"]
    assert losers[0].coin_id == "b"  # worst first


def test_thin_coin_goes_to_high_risk_table(config):
    thin = _row("thin", 50.0, market_cap=1_000_000, volume=1_000)  # well below liquidity filter
    liquid = _row("liquid", 10.0, market_cap=2_000_000_000, volume=50_000_000)
    result = compute_movers([thin, liquid], [], [], set(), config)
    liquid_ids = {r.coin_id for r in result["24h"]["gainers"]}
    high_risk_ids = {r.coin_id for r in result["24h"]["high_risk_gainers"]}
    assert "liquid" in liquid_ids
    assert "thin" not in liquid_ids
    assert "thin" in high_risk_ids


def test_top_n_respected(config):
    config["movers"]["top_n"] = 2
    candidates = [_row(f"c{i}", float(i)) for i in range(10)]
    result = compute_movers(candidates, [], [], set(), config)
    assert len(result["24h"]["gainers"]) == 2


def test_held_flag_set(config):
    candidates = [_row("bitcoin", 5.0)]
    result = compute_movers(candidates, [], [], {"bitcoin"}, config)
    assert result["24h"]["gainers"][0].held is True


def test_classification_and_volume_ratio_populated_from_universe(config):
    coin = make_coin(coin_id="bitcoin", avg_volume_30d=10_000_000)
    cls = make_classification(coin_id="bitcoin", tier="core")
    candidates = [_row("bitcoin", 5.0, volume=30_000_000)]
    result = compute_movers(candidates, [coin], [cls], set(), config)
    row = result["24h"]["gainers"][0]
    assert row.classification == "core"
    assert row.volume_vs_30d_avg == 3.0


def test_missing_pct_change_skips_coin(config):
    row = _row("a", 5.0)
    row["price_change_percentage_1h_in_currency"] = None
    result = compute_movers([row], [], [], set(), config)
    assert result["1h"]["gainers"] == []
