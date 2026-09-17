from __future__ import annotations

from crypto_advisor.insights import (
    ath_52w_insights,
    btc_residual_insights,
    holdings_watchlist_insights,
    moving_average_cross_insights,
    sector_rotation_insights,
    volume_spike_insights,
)

from .conftest import make_coin, make_metrics


def test_volume_spike_fires_above_multiple(config):
    coin = make_coin(coin_id="spikecoin", volume_24h=35_000_000)
    metrics = {"spikecoin": make_metrics("spikecoin", avg_volume_30d_aud=10_000_000)}  # 3.5x -> fires (threshold 3.0)
    insights = volume_spike_insights([coin], metrics, config)
    assert len(insights) == 1
    assert insights[0].rule == "volume_spike"
    assert insights[0].numbers["ratio"] == 3.5


def test_volume_spike_does_not_fire_below_multiple(config):
    coin = make_coin(coin_id="calmcoin", volume_24h=20_000_000)
    metrics = {"calmcoin": make_metrics("calmcoin", avg_volume_30d_aud=10_000_000)}  # 2x -> below 3.0 threshold
    insights = volume_spike_insights([coin], metrics, config)
    assert insights == []


def test_volume_spike_skips_missing_data(config):
    coin = make_coin(coin_id="nodata", volume_24h=None)
    metrics = {"nodata": make_metrics("nodata", avg_volume_30d_aud=None)}
    assert volume_spike_insights([coin], metrics, config) == []


def test_near_ath_fires_within_threshold(config):
    coin = make_coin(coin_id="athcoin", price=98.0, ath=100.0)
    metrics = {"athcoin": make_metrics("athcoin", pct_below_ath=-2.0)}  # within 5%
    insights = ath_52w_insights([coin], metrics, config)
    assert any(i.rule == "near_ath" for i in insights)


def test_near_ath_does_not_fire_outside_threshold(config):
    coin = make_coin(coin_id="farcoin", price=50.0, ath=100.0)
    metrics = {"farcoin": make_metrics("farcoin", pct_below_ath=-50.0)}
    insights = ath_52w_insights([coin], metrics, config)
    assert not any(i.rule == "near_ath" for i in insights)


def test_new_52w_high_fires_at_or_above_prior_high(config):
    coin = make_coin(coin_id="hicoin", price=120.0)
    metrics = {"hicoin": make_metrics("hicoin", week52_high=110.0, week52_low=50.0)}
    insights = ath_52w_insights([coin], metrics, config)
    assert any(i.rule == "new_52w_high" for i in insights)
    assert not any(i.rule == "new_52w_low" for i in insights)


def test_btc_residual_fires_for_large_unexplained_move(config):
    coin = make_coin(coin_id="altcoin", pct_24h=30.0)
    metrics = {"altcoin": make_metrics("altcoin", beta_to_btc_2y=1.0)}
    # BTC moved 2%, beta 1.0 predicts +2% for the coin; actual +30% => residual 28pp >= 15pp threshold
    insights = btc_residual_insights([coin], metrics, btc_24h_change=2.0, config=config)
    assert len(insights) == 1
    assert insights[0].numbers["residual_pct"] == 28.0


def test_btc_residual_does_not_fire_for_beta_explained_move(config):
    coin = make_coin(coin_id="altcoin", pct_24h=4.0)
    metrics = {"altcoin": make_metrics("altcoin", beta_to_btc_2y=2.0)}
    # BTC +2%, beta 2.0 predicts +4%, actual +4% -> residual 0
    insights = btc_residual_insights([coin], metrics, btc_24h_change=2.0, config=config)
    assert insights == []


def test_btc_residual_skips_bitcoin_itself(config):
    coin = make_coin(coin_id="bitcoin", pct_24h=50.0)
    metrics = {"bitcoin": make_metrics("bitcoin", beta_to_btc_2y=1.0)}
    assert btc_residual_insights([coin], metrics, btc_24h_change=2.0, config=config) == []


def test_sector_rotation_fires_above_spread_threshold(config):
    categories = [
        {"name": "AI", "market_cap_change_24h": 10.0},
        {"name": "Memes", "market_cap_change_24h": -5.0},  # 15pp spread >= 8.0
    ]
    insights = sector_rotation_insights(categories, config)
    assert len(insights) == 1
    assert insights[0].numbers["spread"] == 15.0


def test_sector_rotation_does_not_fire_below_spread(config):
    categories = [
        {"name": "AI", "market_cap_change_24h": 2.0},
        {"name": "Memes", "market_cap_change_24h": -1.0},  # 3pp spread < 8.0
    ]
    assert sector_rotation_insights(categories, config) == []


def test_holdings_big_move_fires_for_held_coin_above_threshold(config):
    coin = make_coin(coin_id="held1", pct_24h=9.0)  # >= alerts threshold 8.0
    universe_by_id = {"held1": coin}
    insights = holdings_watchlist_insights(universe_by_id, {"held1"}, set(), config)
    assert len(insights) == 1
    assert "holding" in insights[0].message


def test_holdings_big_move_does_not_fire_below_threshold(config):
    coin = make_coin(coin_id="held1", pct_24h=3.0)
    universe_by_id = {"held1": coin}
    assert holdings_watchlist_insights(universe_by_id, {"held1"}, set(), config) == []


def test_watchlist_move_tagged_differently_from_holding(config):
    coin = make_coin(coin_id="watch1", pct_24h=15.0)
    universe_by_id = {"watch1": coin}
    insights = holdings_watchlist_insights(universe_by_id, set(), {"watch1"}, config)
    assert "watchlist" in insights[0].message


def _crafted_cross_up_prices() -> list[float]:
    baseline = [100.0] * 248
    yesterday_window = [110.0] * 49 + [90.0]  # last element (index -2 overall) is "yesterday's" close
    today_price = [150.0]
    return baseline + yesterday_window + today_price


def test_moving_average_cross_up_detected(config):
    prices = _crafted_cross_up_prices()
    daily_prices = [(i * 86_400_000, p) for i, p in enumerate(prices)]
    coin = make_coin(coin_id="crosser", daily_prices=daily_prices, history_days=len(prices))
    insights = moving_average_cross_insights([coin], config)
    assert any(i.rule.endswith("_cross_up") for i in insights)
    assert not any(i.rule.endswith("_cross_down") for i in insights)


def test_moving_average_no_cross_for_flat_prices(config):
    prices = [100.0] * 300
    daily_prices = [(i * 86_400_000, p) for i, p in enumerate(prices)]
    coin = make_coin(coin_id="flat", daily_prices=daily_prices, history_days=len(prices))
    insights = moving_average_cross_insights([coin], config)
    assert insights == []
