from __future__ import annotations

import crypto_advisor.universe as universe_mod
from crypto_advisor.universe import UniverseCoin, _build_coin_from_row, _is_major_exchange_listed, build_universe


class FakeCG:
    """Minimal CoinGeckoClient stand-in. No network -- everything is canned."""

    def __init__(self, category_rows=None, market_rows=None, chart_by_id=None, tickers_by_id=None):
        self.category_rows = category_rows or {}
        self.market_rows = market_rows or []
        self.chart_by_id = chart_by_id or {}
        self.tickers_by_id = tickers_by_id or {}

    def coins_markets(self, vs_currency, ids=None, category=None, page=1, per_page=250, price_change_percentage=None):
        if category:
            return self.category_rows.get(category, []) if page == 1 else []
        return self.market_rows if page == 1 else []

    def coin_market_chart(self, coin_id, vs_currency, days):
        return self.chart_by_id.get(coin_id)

    def coin_tickers(self, coin_id):
        return self.tickers_by_id.get(coin_id, [])


def _make_chart(days=800, price=100.0, volume=20_000_000):
    prices = [[i * 86_400_000, price] for i in range(days)]
    volumes = [[i * 86_400_000, volume] for i in range(days)]
    return {"prices": prices, "total_volumes": volumes}


def _tickers_on(exchange_name):
    return [{"market": {"name": exchange_name}, "converted_volume": {"usd": 1_000_000}}]


def test_excludes_stablecoin_category(config, monkeypatch):
    excluded_calls = []
    monkeypatch.setattr(universe_mod, "log_excluded", lambda *a, **k: excluded_calls.append(a))

    cg = FakeCG(
        category_rows={"stablecoins": [{"id": "tether", "symbol": "usdt", "market_cap": 8e10, "current_price": 1.5}]},
        market_rows=[
            {"id": "tether", "symbol": "usdt", "market_cap": 8e10, "current_price": 1.5},
            {"id": "bitcoin", "symbol": "btc", "market_cap": 2e12, "current_price": 90000.0},
        ],
        chart_by_id={"bitcoin": _make_chart()},
        tickers_by_id={"bitcoin": _tickers_on("Kraken")},
    )
    univ, movers_pool = build_universe(cg, config)
    ids = {c.coin_id for c in univ}
    assert "tether" not in ids
    assert "bitcoin" in ids
    assert any(call[0] == "tether" and "excluded_category" in call[2] for call in excluded_calls)
    # movers pool keeps only category/denylist exclusions applied -- tether stays out, bitcoin stays in
    assert "tether" not in {r["id"] for r in movers_pool}
    assert "bitcoin" in {r["id"] for r in movers_pool}


def test_excludes_symbol_denylist(config, monkeypatch):
    excluded_calls = []
    monkeypatch.setattr(universe_mod, "log_excluded", lambda *a, **k: excluded_calls.append(a))
    cg = FakeCG(market_rows=[{"id": "wrapped-bitcoin", "symbol": "wbtc", "market_cap": 5e9, "current_price": 90000.0}])
    univ, _ = build_universe(cg, config)
    assert univ == []
    assert any(call[2] == "excluded_symbol_denylist" for call in excluded_calls)


def test_excludes_below_min_market_cap(config, monkeypatch):
    excluded_calls = []
    monkeypatch.setattr(universe_mod, "log_excluded", lambda *a, **k: excluded_calls.append(a))
    cg = FakeCG(market_rows=[{"id": "tinycoin", "symbol": "tiny", "market_cap": 1_000_000, "current_price": 0.01}])
    univ, _ = build_universe(cg, config)
    assert univ == []
    assert any(call[2] == "below_min_market_cap" for call in excluded_calls)


def test_excludes_insufficient_history(config, monkeypatch):
    excluded_calls = []
    monkeypatch.setattr(universe_mod, "log_excluded", lambda *a, **k: excluded_calls.append(a))
    cg = FakeCG(
        market_rows=[{"id": "newcoin", "symbol": "new", "market_cap": 5e9, "current_price": 10.0}],
        chart_by_id={"newcoin": _make_chart(days=100)},  # well under min_price_history_days=730
        tickers_by_id={"newcoin": _tickers_on("Kraken")},
    )
    univ, _ = build_universe(cg, config)
    assert univ == []
    assert any(call[2] == "insufficient_price_history_days" for call in excluded_calls)


def test_excludes_not_on_major_exchange(config, monkeypatch):
    excluded_calls = []
    monkeypatch.setattr(universe_mod, "log_excluded", lambda *a, **k: excluded_calls.append(a))
    cg = FakeCG(
        market_rows=[{"id": "obscure", "symbol": "obs", "market_cap": 5e9, "current_price": 10.0}],
        chart_by_id={"obscure": _make_chart()},
        tickers_by_id={"obscure": [{"market": {"name": "SomeTinyDex"}, "converted_volume": {"usd": 1000}}]},
    )
    univ, _ = build_universe(cg, config)
    assert univ == []
    assert any(call[2] == "not_on_major_exchange" for call in excluded_calls)


def test_passes_all_filters(config, monkeypatch):
    monkeypatch.setattr(universe_mod, "log_excluded", lambda *a, **k: None)
    cg = FakeCG(
        market_rows=[{"id": "goodcoin", "symbol": "good", "market_cap": 5e9, "current_price": 10.0}],
        chart_by_id={"goodcoin": _make_chart()},
        tickers_by_id={"goodcoin": _tickers_on("Binance")},
    )
    univ, _ = build_universe(cg, config)
    assert len(univ) == 1
    assert univ[0].coin_id == "goodcoin"
    assert univ[0].avg_volume_30d_aud == 20_000_000


def test_is_major_exchange_listed_case_insensitive_substring():
    tickers = [{"market": {"name": "Binance"}}, {"market": {"name": "SomeSmallDex"}}]
    listed = _is_major_exchange_listed(tickers, ["binance", "Coinbase Exchange"])
    assert listed == ["Binance"]
