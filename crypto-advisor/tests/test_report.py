from __future__ import annotations

from datetime import datetime, timezone

import crypto_advisor.report as report_mod
from crypto_advisor.config import Portfolio
from crypto_advisor.movers import MoverRow
from crypto_advisor.report import ReportContext, write_simple_report
from crypto_advisor.risk import FinalAction
from crypto_advisor.signals import ADD, BUY, SELL, WATCH

from .conftest import make_coin


def _mover(coin_id, symbol, pct, held=False):
    return MoverRow(coin_id=coin_id, symbol=symbol, name=coin_id, price_aud=10.0, pct_change=pct,
                     volume_24h_aud=1_000_000, volume_vs_30d_avg=1.0, market_cap_aud=1_000_000_000,
                     classification="speculative", held=held)


def _action(coin_id, action, score, confidence="medium"):
    return FinalAction(coin_id=coin_id, action=action, original_signal_action=action, confidence=confidence,
                        score=score, held=False)


def _base_ctx(config, movers, final_actions, universe=None) -> ReportContext:
    return ReportContext(
        universe=universe or [], metrics_by_id={}, classifications=[], movers=movers, insights=[],
        global_data=None, categories=[], final_actions=final_actions,
        portfolio=Portfolio(cash_aud=0.0, holdings=[], watchlist=[]), summary_text=None,
        fetch_time=datetime.now(timezone.utc), stale_sources=[], config=config,
    )


def _empty_movers():
    return {"24h": {"gainers": [], "losers": [], "high_risk_gainers": [], "high_risk_losers": []}}


def test_simple_report_lists_gainers_above_threshold(config, tmp_path, monkeypatch):
    monkeypatch.setattr(report_mod, "OUTPUT_DIR", tmp_path)
    movers = _empty_movers()
    movers["24h"]["gainers"] = [_mover("a", "AAA", 25.0), _mover("b", "BBB", 15.0)]
    ctx = _base_ctx(config, movers, [])
    path = write_simple_report(ctx)
    text = path.read_text()
    assert "AAA +25.0%" in text
    assert "BBB" not in text  # below the 20% threshold


def test_simple_report_no_gainers_says_so(config, tmp_path, monkeypatch):
    monkeypatch.setattr(report_mod, "OUTPUT_DIR", tmp_path)
    ctx = _base_ctx(config, _empty_movers(), [])
    text = write_simple_report(ctx).read_text()
    assert "None moved more than +20%" in text


def test_simple_report_flags_thin_liquidity_movers(config, tmp_path, monkeypatch):
    monkeypatch.setattr(report_mod, "OUTPUT_DIR", tmp_path)
    movers = _empty_movers()
    movers["24h"]["high_risk_gainers"] = [_mover("thin", "THIN", 40.0)]
    ctx = _base_ctx(config, movers, [])
    text = write_simple_report(ctx).read_text()
    assert "THIN +40.0%" in text
    assert "high risk" in text


def test_simple_report_losers_below_negative_threshold(config, tmp_path, monkeypatch):
    monkeypatch.setattr(report_mod, "OUTPUT_DIR", tmp_path)
    movers = _empty_movers()
    movers["24h"]["losers"] = [_mover("c", "CCC", -30.0), _mover("d", "DDD", -5.0)]
    ctx = _base_ctx(config, movers, [])
    text = write_simple_report(ctx).read_text()
    assert "CCC -30.0%" in text
    assert "DDD" not in text


def test_simple_report_lists_buy_add_potentials(config, tmp_path, monkeypatch):
    monkeypatch.setattr(report_mod, "OUTPUT_DIR", tmp_path)
    coin = make_coin(coin_id="goodcoin", history_days=100)
    actions = [_action("goodcoin", BUY, 0.8), _action("watched", WATCH, 0.6)]
    ctx = _base_ctx(config, _empty_movers(), actions, universe=[coin])
    text = write_simple_report(ctx).read_text()
    assert "clear the bar for BUY/ADD" in text
    assert "goodcoin" in text
    assert "watched" not in text  # WATCH isn't shown once a real BUY/ADD exists


def test_simple_report_falls_back_to_closest_when_no_buy_add(config, tmp_path, monkeypatch):
    monkeypatch.setattr(report_mod, "OUTPUT_DIR", tmp_path)
    actions = [_action("watched", WATCH, 0.6), _action("sold", SELL, 0.1)]
    ctx = _base_ctx(config, _empty_movers(), actions)
    text = write_simple_report(ctx).read_text()
    assert "No coin currently clears the bar" in text
    assert "watched" in text
    assert "sold" not in text  # SELL/TRIM never shown as a "potential"


def test_simple_report_never_claims_a_forecast(config, tmp_path, monkeypatch):
    monkeypatch.setattr(report_mod, "OUTPUT_DIR", tmp_path)
    ctx = _base_ctx(config, _empty_movers(), [])
    text = write_simple_report(ctx).read_text().lower()
    assert "not a prediction" in text
    assert "not financial advice" in text
