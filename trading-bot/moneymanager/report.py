"""Performance statistics."""
from __future__ import annotations

import math

from .portfolio import Portfolio


def summarize(pf: Portfolio, periods_per_year: int = 252) -> dict:
    eq = [e for _, e in pf.equity_curve]
    if len(eq) < 2:
        return {"final_equity": pf.equity}
    rets = [b / a - 1 for a, b in zip(eq, eq[1:]) if a > 0]
    mean = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1))
    downside = [r for r in rets if r < 0]
    dsd = math.sqrt(sum(r * r for r in downside) / len(downside)) if downside else 0.0
    peak, mdd = eq[0], 0.0
    for e in eq:
        peak = max(peak, e)
        mdd = max(mdd, 1 - e / peak)
    years = len(eq) / periods_per_year
    cagr = (eq[-1] / eq[0]) ** (1 / years) - 1 if years > 0 and eq[0] > 0 and eq[-1] > 0 else 0.0
    trades = pf.closed_trades
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t < 0]
    return {
        "start_equity": round(eq[0], 2),
        "final_equity": round(eq[-1], 2),
        "total_return_pct": round((eq[-1] / eq[0] - 1) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(mdd * 100, 2),
        "sharpe": round(mean / sd * math.sqrt(periods_per_year), 2) if sd else 0.0,
        "sortino": round(mean / dsd * math.sqrt(periods_per_year), 2) if dsd else 0.0,
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses else None,
        "fills": len(pf.fills),
    }
