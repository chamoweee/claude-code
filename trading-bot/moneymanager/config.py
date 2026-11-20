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


def build_from_config(cfg: dict, base_dir: Path | None = None) -> Engine:
    base_dir = base_dir or Path.cwd()
    if cfg.get("broker", "paper") != "paper":
        raise ValueError("Only the paper broker is wired into the CLI. Live brokers must be built in code "
                         "deliberately (see moneymanager/brokers/ccxt_broker.py).")
    pf = Portfolio(float(cfg.get("starting_cash", 100_000)))
    mm = MoneyManager(
        portfolio=pf,
        sizer=build_sizer(cfg.get("sizing", {})),
        risk=RiskManager(RiskLimits.from_dict(cfg.get("risk", {}))),
        broker=PaperBroker(),
        allocations=cfg.get("allocations", {}),
        default_allocation=cfg.get("default_allocation", 1.0),
        trail_stops=cfg.get("trail_stops", True),
    )
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
        strat_cfg = dict(m.get("strategy", default_strategy))
        if strat_cfg.get("type", "trend") == "trend":
            strat_cfg.setdefault("allow_short", inst.allow_short)
        markets.append(Market(inst, bars, build_strategy(strat_cfg)))
    return Engine(mm, markets)


def load_config(path: str | Path) -> tuple[dict, Path]:
    p = Path(path)
    return json.loads(p.read_text()), p.parent
