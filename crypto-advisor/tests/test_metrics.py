from __future__ import annotations

import numpy as np
import pytest

from crypto_advisor.metrics import (
    annualized_volatility_pct,
    compute_ccxt_volume_check,
    correlation_and_beta,
    historical_weekly_return_range,
    max_drawdown_pct,
    sma,
)

from .conftest import make_coin


def test_max_drawdown_pct_known_series():
    # Running peak hits 120 at idx 1, troughs at 50 at idx 2 => (50-120)/120 = -58.33%
    prices = [100, 120, 50, 80, 130]
    dd = max_drawdown_pct(prices)
    assert dd == pytest.approx((50 - 120) / 120 * 100, rel=1e-6)


def test_max_drawdown_simple_halving():
    prices = [100, 50]
    assert max_drawdown_pct(prices) == pytest.approx(-50.0)


def test_max_drawdown_no_decline():
    prices = [100, 110, 120, 130]
    assert max_drawdown_pct(prices) == pytest.approx(0.0)


def test_max_drawdown_insufficient_data():
    assert max_drawdown_pct([100]) is None
    assert max_drawdown_pct([]) is None


def test_sma_basic():
    prices = [1, 2, 3, 4, 5]
    assert sma(prices, 5) == pytest.approx(3.0)
    assert sma(prices, 3) == pytest.approx(4.0)  # last 3: 3,4,5
    assert sma(prices, 10) is None  # not enough data


def test_annualized_volatility_zero_for_constant_prices():
    prices = [100.0] * 40
    vol = annualized_volatility_pct(prices, 30)
    assert vol == pytest.approx(0.0, abs=1e-9)


def test_annualized_volatility_positive_for_noisy_prices():
    rng = np.random.default_rng(42)
    prices = [100.0]
    for _ in range(100):
        prices.append(prices[-1] * (1 + rng.normal(0, 0.02)))
    vol = annualized_volatility_pct(prices, 90)
    assert vol is not None and vol > 0


def test_annualized_volatility_insufficient_data_returns_none():
    assert annualized_volatility_pct([100, 101, 102], 30) is None


def test_correlation_and_beta_perfect_positive_correlation():
    rng = np.random.default_rng(3)
    returns = rng.normal(0, 0.02, 200)
    btc = [100.0]
    coin = [50.0]  # same returns, different price scale -- should still be corr=1, beta=1
    for r in returns:
        btc.append(btc[-1] * (1 + r))
        coin.append(coin[-1] * (1 + r))
    corr, beta = correlation_and_beta(coin, btc)
    assert corr == pytest.approx(1.0, abs=1e-6)
    assert beta == pytest.approx(1.0, abs=1e-6)


def test_correlation_and_beta_amplified_moves_gives_higher_beta():
    rng = np.random.default_rng(7)
    btc_returns = rng.normal(0, 0.02, 200)
    btc = [100.0]
    coin = [50.0]
    for r in btc_returns:
        btc.append(btc[-1] * (1 + r))
        coin.append(coin[-1] * (1 + 2 * r))  # coin moves 2x BTC's return each day
    corr, beta = correlation_and_beta(coin, btc)
    assert beta == pytest.approx(2.0, abs=0.05)


def test_correlation_and_beta_insufficient_data_returns_none():
    corr, beta = correlation_and_beta([100, 101], [100, 101])
    assert corr is None and beta is None


class _FakeCcxtClient:
    """ccxt OHLCV rows: [ts, open, high, low, close, volume_in_base_asset]."""
    exchange_id = "kraken"

    def daily_ohlcv(self, symbol, quote="USD", days=45):
        # 100 BTC/day traded at a $50,000 close -> $5,000,000 USD notional/day,
        # not $100 (the bug regressed here treated raw base volume as USD).
        return [[i, 50_000, 50_000, 50_000, 50_000, 100] for i in range(35)]


def test_ccxt_volume_check_converts_base_volume_to_usd_notional():
    coin = make_coin(coin_id="bitcoin", symbol="btc", avg_volume_30d=7_500_000)  # AUD
    exchange_id, avg_volume_usd, note = compute_ccxt_volume_check(_FakeCcxtClient(), coin, usd_to_aud_rate=1.5)
    assert exchange_id == "kraken"
    # 100 base units * $50,000 close = $5,000,000/day USD notional
    assert avg_volume_usd == pytest.approx(5_000_000)


def test_ccxt_volume_check_returns_none_without_client():
    coin = make_coin(coin_id="bitcoin")
    assert compute_ccxt_volume_check(None, coin, usd_to_aud_rate=1.5) == (None, None, None)


def test_historical_weekly_return_range_insufficient_history_returns_none():
    assert historical_weekly_return_range([100.0] * 5) is None
    assert historical_weekly_return_range([100.0] * 12) is None  # <10 weekly samples


def test_historical_weekly_return_range_zero_for_constant_prices():
    rng = historical_weekly_return_range([100.0] * 50)
    assert rng is not None
    assert rng["p10"] == pytest.approx(0.0)
    assert rng["median"] == pytest.approx(0.0)
    assert rng["p90"] == pytest.approx(0.0)
    assert rng["samples"] == 50 - 7


def test_historical_weekly_return_range_known_step_series():
    # Every 7th day the price doubles, held flat in between -> every trailing
    # 7-day return is exactly +100%.
    prices = []
    price = 100.0
    for week in range(15):
        for _ in range(7):
            prices.append(price)
        price *= 2
    rng = historical_weekly_return_range(prices)
    assert rng["median"] == pytest.approx(100.0, rel=0.05)


def test_historical_weekly_return_range_never_uses_future_data():
    # The stat is a description of the past, not a prediction: it must be
    # computable purely from a prefix of history (no look-ahead).
    rng_full = historical_weekly_return_range(list(range(100, 200)))
    rng_prefix = historical_weekly_return_range(list(range(100, 150)))
    assert rng_full is not None and rng_prefix is not None
    assert rng_full != rng_prefix  # different history -> different (real) stat, no leakage from the future
