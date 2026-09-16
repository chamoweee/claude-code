"""Event-driven backtest engine: single symbol, next-bar-only execution.

A signal computed from bar i's close is acted on at bar i+1's open — never
at bar i's own close or open. This is the main defence against look-ahead
bias: you cannot backtest "buy at today's open" using information only
known at today's close.

Multi-symbol / portfolio-level backtesting (spreading RISK.max_open_positions
across the universe at once) is a deliberate next increment, not done here —
this engine proves the mechanics correctly for one symbol first.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradesys.backtest.costs import trade_cost
from tradesys.backtest.portfolio import Portfolio
from tradesys.config import RISK
from tradesys.risk.sizing import position_size
from tradesys.strategies.base import Strategy


@dataclass
class BacktestResult:
    portfolio: Portfolio
    equity_curve: pd.DataFrame
    trade_log: pd.DataFrame
    final_equity: float


def run_single_symbol_backtest(
    bars: pd.DataFrame,
    strategy: Strategy,
    symbol: str,
    starting_capital: float,
    is_foreign: bool = False,
) -> BacktestResult:
    bars = bars.sort_values("date").reset_index(drop=True)
    signals = strategy.generate_signals(bars)
    if len(signals) != len(bars):
        raise ValueError("generate_signals must return one value per bar")

    portfolio = Portfolio(cash=starting_capital)
    position_open = False

    n = len(bars)
    for i in range(n - 1):
        today = bars.iloc[i]
        next_bar = bars.iloc[i + 1]
        signal_today = signals.iloc[i]

        # Mark to market BEFORE acting on today's signal: the trade it leads
        # to executes at next_bar's open, so it must not affect today's
        # valuation — only from next_bar's own mark onward.
        portfolio.mark_to_market(today["date"], {symbol: float(today["close"])})

        if signal_today == 1 and not position_open:
            entry_price = float(next_bar["open"])
            equity_before = portfolio.cash  # flat, so equity == cash here
            if strategy.sizing_mode == "full_capital":
                qty = int(portfolio.cash // entry_price)
            else:
                stop_price = entry_price * (1 - strategy.stop_loss_pct)
                qty = position_size(
                    equity_aud=equity_before,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    cash_available_aud=portfolio.cash,
                    risk_pct=RISK.max_risk_per_trade_pct,
                )
            if qty > 0:
                cost = trade_cost(qty * entry_price, is_foreign)["total"]
                # Leave room for the cost on top of the shares themselves.
                while qty > 0 and qty * entry_price + trade_cost(qty * entry_price, is_foreign)["total"] > portfolio.cash:
                    qty -= 1
                if qty > 0:
                    cost = trade_cost(qty * entry_price, is_foreign)["total"]
                    portfolio.buy(next_bar["date"], symbol, entry_price, qty, cost)
                    position_open = True

        elif signal_today == 0 and position_open:
            exit_price = float(next_bar["open"])
            qty_held = portfolio.positions[symbol].qty
            cost = trade_cost(qty_held * exit_price, is_foreign)["total"]
            portfolio.sell(next_bar["date"], symbol, exit_price, qty_held, cost)
            position_open = False

    # Mark the final bar too (no more trading decisions possible after it).
    last = bars.iloc[-1]
    portfolio.mark_to_market(last["date"], {symbol: float(last["close"])})

    equity_curve = pd.DataFrame(portfolio.equity_curve)
    trade_log = pd.DataFrame(portfolio.trade_log)
    final_equity = equity_curve["equity"].iloc[-1] if not equity_curve.empty else starting_capital

    return BacktestResult(
        portfolio=portfolio,
        equity_curve=equity_curve,
        trade_log=trade_log,
        final_equity=final_equity,
    )
