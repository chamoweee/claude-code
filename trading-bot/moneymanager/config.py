"""Build a full MoneyManager + Engine from a JSON config."""
from __future__ import annotations

import json
from pathlib import Path

from .brokers.paper import PaperBroker
from .data import load_csv, synthetic
from .engine import Engine, Market, MoneyManager
from .models import AssetClass, Instrument
from .portfolio import Portfolio
from .risk import RiskLimits, RiskManager
from .sizing import build_sizer
from .strategy import build_strategy

INSTRUMENT_FIELDS = {"multiplier", "lot_size", "min_qty", "allow_short", "commission_per_unit",
                     "commission_pct", "slippage_pct"}


def build_broker(cfg: dict, allow_live: bool):
    bcfg = cfg.get("broker", "paper")
    if bcfg == "paper" or (isinstance(bcfg, dict) and bcfg.get("type") == "paper"):
        return PaperBroker()
    if not allow_live:
        raise ValueError("This config uses a live broker. Live trading only runs with "
                         "`trade --live` (and MONEYMANAGER_LIVE=1). Use \"broker\": \"paper\" otherwise.")
    if isinstance(bcfg, dict) and bcfg.get("type") == "ccxt":
        non_crypto = [m["symbol"] for m in cfg["markets"] if m["asset_class"] != "crypto"]
        if non_crypto:
            raise ValueError(f"The ccxt broker only trades crypto; remove or paper-trade: {non_crypto}")
        from .brokers.ccxt_broker import CCXTBroker
        return CCXTBroker(bcfg.get("exchange", "binance"), live=True, sandbox=bcfg.get("sandbox", True))
    raise ValueError(f"unknown broker config: {bcfg!r}")


def build_from_config(cfg: dict, base_dir: Path | None = None, allow_live: bool = False,
                      ai_client=None) -> Engine:
    base_dir = base_dir or Path.cwd()
    pf = Portfolio(float(cfg.get("starting_cash", 100_000)))
    mm = MoneyManager(
        portfolio=pf,
        sizer=build_sizer(cfg.get("sizing", {})),
        risk=RiskManager(RiskLimits.from_dict(cfg.get("risk", {}))),
        broker=build_broker(cfg, allow_live),
        allocations=cfg.get("allocations", {}),
        default_allocation=cfg.get("default_allocation", 1.0),
        trail_stops=cfg.get("trail_stops", True),
    )
    ai_cfg = cfg.get("ai", {})
    ai_on = ai_cfg.get("enabled", False)
    default_strategy = cfg.get("strategy", {"type": "trend"})
    markets = []
    for i, m in enumerate(cfg["markets"]):
        inst = Instrument(symbol=m["symbol"], asset_class=AssetClass(m["asset_class"]),
                          **{k: v for k, v in m.items() if k in INSTRUMENT_FIELDS})
        data = m.get("data", {"synthetic": {}})
        if "csv" in data:
            bars = load_csv(base_dir / data["csv"])
        else:
            syn = dict(data.get("synthetic", {}))
            syn.setdefault("seed", i + 1)
            syn.setdefault("start_price", 100.0)
            bars = synthetic(**syn)
        if ai_on and "strategy" not in m:
            strategy = None  # the AI agent decides for this market
        else:
            strat_cfg = dict(m.get("strategy", default_strategy))
            if strat_cfg.get("type", "trend") == "trend":
                strat_cfg.setdefault("allow_short", inst.allow_short)
            strategy = build_strategy(strat_cfg)
        markets.append(Market(inst, bars, strategy))

    portfolio_strategy = None
    if ai_on:
        from .ai_agent import ClaudeTrader
        params = {k: v for k, v in ai_cfg.items() if k not in ("enabled", "decide_every")}
        if params.get("journal"):
            params["journal"] = base_dir / params["journal"]
        portfolio_strategy = ClaudeTrader(client=ai_client, **params)
    return Engine(mm, markets, portfolio_strategy=portfolio_strategy,
                  decide_every=ai_cfg.get("decide_every", 1))


def load_config(path: str | Path) -> tuple[dict, Path]:
    p = Path(path)
    return json.loads(p.read_text()), p.parent
