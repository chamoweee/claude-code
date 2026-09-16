"""Single source of truth for account and risk parameters.

Nothing else in this codebase should hard-code these numbers — import them
from here so a change in one place propagates everywhere (backtest, risk
sizing, and the go-live gate all read the same config).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class AccountConfig:
    starting_capital_aud: float = 2000.0
    contribution_aud: float = 500.0
    contribution_period_days: int = 14  # fortnightly
    timezone: str = "Australia/Sydney"


@dataclass(frozen=True)
class RiskConfig:
    # Fraction of current account equity risked on a single trade (distance
    # from entry to stop-loss, sized so a stop-out costs this much).
    max_risk_per_trade_pct: float = 0.01
    max_open_positions: int = 3
    # Daily realized-loss halt: stop opening new positions for the rest of
    # the day once realized P&L drops below -this fraction of equity.
    daily_loss_halt_pct: float = 0.02
    # Equity drawdown from peak that halts the whole system and requires a
    # human to look at it before anything resumes.
    max_drawdown_halt_pct: float = 0.10


@dataclass(frozen=True)
class GoLiveCriteria:
    """A strategy must pass ALL of these, measured on held-out data, before
    execution/go_live_gate.py will allow live mode."""

    must_beat_benchmark_after_fees: bool = True
    min_trades_for_expectancy: int = 100
    max_acceptable_drawdown_pct: float = 0.15
    min_paper_trading_days: int = 90
    # How far paper-trading performance is allowed to diverge from what the
    # backtest predicted for the same period before we call it a mismatch.
    max_paper_vs_backtest_divergence_pct: float = 0.30


@dataclass(frozen=True)
class CostConfig:
    # CMC Invest / typical AU broker-style flat-ish fee structure — adjust
    # to match your actual broker's schedule before trusting P&L numbers.
    min_brokerage_aud: float = 9.90
    brokerage_pct_of_notional: float = 0.0008  # 0.08%
    assumed_spread_pct: float = 0.0005  # 0.05%, applied against the trader
    assumed_slippage_pct: float = 0.0005  # 0.05%, applied against the trader
    fx_cost_pct: float = 0.005  # for any non-AUD instrument (e.g. US ETFs)


ACCOUNT = AccountConfig()
RISK = RiskConfig()
GO_LIVE = GoLiveCriteria()
COSTS = CostConfig()

# Fixed, hand-picked universe — chosen up front and never revised based on
# hindsight of "what performed well", to avoid survivorship/selection bias.
# Benchmarks first, then liquid ASX large-caps spanning several sectors.
BENCHMARK_SYMBOLS: list[str] = ["VAS", "IVV"]
UNIVERSE_SYMBOLS: list[str] = [
    "CBA", "BHP", "CSL", "NAB", "WBC", "ANZ",
    "WES", "WOW", "MQG", "TLS", "RIO", "WDS",
]
ASX_EXCHANGE = "ASX"

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")

DATA_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data_cache")
