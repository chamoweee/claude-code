"""Save and restore the bot's state so auto-trading survives restarts."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .engine import Engine
from .models import Position


def save_state(engine: Engine, path: str | Path, last_seen: dict[str, str]) -> None:
    pf, risk = engine.mm.portfolio, engine.mm.risk
    data = {
        "cash": pf.cash,
        "starting_cash": pf.starting_cash,
        "high_water_mark": pf.high_water_mark,
        "day_start_equity": pf.day_start_equity,
        "current_day": pf.current_day,
        "closed_trades": pf.closed_trades[-500:],
        "halted": risk.halted,
        "halt_reason": risk.halt_reason,
        "last_seen": last_seen,
        "positions": {
            s: {"qty": p.qty, "avg_price": p.avg_price, "stop_price": p.stop_price,
                "last_price": p.last_price, "realized_pnl": p.realized_pnl, "entry_risk": p.entry_risk}
            for s, p in pf.positions.items() if p.is_open or p.realized_pnl
        },
    }
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)  # atomic: a crash mid-write never leaves a half-written state file


def load_state(engine: Engine, path: str | Path) -> dict[str, str]:
    """Restore into a freshly built engine. Returns last processed bar time per symbol."""
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    pf, risk = engine.mm.portfolio, engine.mm.risk
    pf.cash = data["cash"]
    pf.high_water_mark = data["high_water_mark"]
    pf.day_start_equity = data["day_start_equity"]
    pf.current_day = data["current_day"]
    pf.closed_trades = list(data.get("closed_trades", []))
    risk.halted = data.get("halted", False)
    risk.halt_reason = data.get("halt_reason", "")
    engine._halt_handled = risk.halted
    for sym, p in data.get("positions", {}).items():
        if sym not in engine.markets:
            raise ValueError(f"state has a position in {sym}, which is no longer in the config. "
                             "Close it or add the market back before restarting.")
        pf.positions[sym] = Position(engine.markets[sym].instrument, **p)
    return dict(data.get("last_seen", {}))
