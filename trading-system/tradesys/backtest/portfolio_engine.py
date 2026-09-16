"""Cross-sectional momentum ("dual momentum" style) portfolio backtest.

Different in kind from the single-symbol Strategy rules, not just a
retuned version of them: instead of asking "is THIS stock's own price
pattern a buy signal", it asks "which of the whole universe currently has
the strongest trailing trend", holds the top K, and goes to cash for any
slot where nothing in the universe has positive momentum at all. This is
the actual mechanism behind published cross-sectional/dual momentum
research (Jegadeesh & Titman; Antonacci) — a genuinely different strategy
design, not a parameter search over the earlier single-symbol rules.

Rebalances on a fixed schedule (every `rebalance_every_days` trading days)
using each symbol's trailing return over `lookback_days` as of that day's
close, executes at the NEXT trading day's open (same no-look-ahead rule as
the single-symbol engine), and requires all symbols to share the same
trading-day calendar (build the `symbol_bars` dict from bars already
aligned to a common date index before calling this).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradesys.backtest.costs import trade_cost
from tradesys.backtest.portfolio import Portfolio


@dataclass
class PortfolioBacktestResult:
    portfolio: Portfolio
    equity_curve: pd.DataFrame
    trade_log: pd.DataFrame
    final_equity: float
    rebalance_log: list[dict]


def _momentum_score(closes: pd.Series, i: int, lookback_days: int) -> float | None:
    if i - lookback_days < 0:
        return None
    past = closes.iloc[i - lookback_days]
    if past <= 0:
        return None
    return closes.iloc[i] / past - 1


def run_cross_sectional_momentum_backtest(
    symbol_bars: dict[str, pd.DataFrame],
    starting_capital: float,
    lookback_days: int = 126,
    rebalance_every_days: int = 21,
    top_k: int = 3,
    require_positive_momentum: bool = True,
) -> PortfolioBacktestResult:
    symbols = list(symbol_bars.keys())
    dates = symbol_bars[symbols[0]]["date"].reset_index(drop=True)
    closes = {s: symbol_bars[s].sort_values("date")["close"].reset_index(drop=True) for s in symbols}
    opens = {s: symbol_bars[s].sort_values("date")["open"].reset_index(drop=True) for s in symbols}
    for s in symbols:
        if not symbol_bars[s]["date"].reset_index(drop=True).equals(dates):
            raise ValueError(f"{s} is not aligned to the same date index as {symbols[0]}")

    portfolio = Portfolio(cash=starting_capital)
    rebalance_log: list[dict] = []
    n = len(dates)

    for i in range(n - 1):
        current_prices = {s: float(closes[s].iloc[i]) for s in symbols}
        portfolio.mark_to_market(dates.iloc[i], current_prices)

        is_rebalance_day = i >= lookback_days and i % rebalance_every_days == 0
        if not is_rebalance_day:
            continue

        scores = {}
        for s in symbols:
            score = _momentum_score(closes[s], i, lookback_days)
            if score is not None:
                scores[s] = score

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        if require_positive_momentum:
            ranked = [(s, sc) for s, sc in ranked if sc > 0]
        target_symbols = [s for s, _ in ranked[:top_k]]

        rebalance_log.append(
            {"date": dates.iloc[i], "ranked": ranked[:top_k], "target": list(target_symbols)}
        )

        held_symbols = list(portfolio.positions.keys())
        next_prices_open = {s: float(opens[s].iloc[i + 1]) for s in symbols}

        # Sell anything no longer in the target set.
        for s in held_symbols:
            if s not in target_symbols:
                qty = portfolio.positions[s].qty
                price = next_prices_open[s]
                cost = trade_cost(qty * price)["total"]
                portfolio.sell(dates.iloc[i + 1], s, price, qty, cost)

        # Equity available to deploy, computed AFTER exits above.
        equity_now = portfolio.cash + portfolio.market_value(current_prices)
        target_weight = 1.0 / top_k if target_symbols else 0.0

        for s in target_symbols:
            if s in portfolio.positions:
                continue  # already held, no drift-rebalancing in this simple version
            price = next_prices_open[s]
            notional = equity_now * target_weight
            qty = int(notional // price)
            if qty <= 0:
                continue
            cost = trade_cost(qty * price)["total"]
            while qty > 0 and qty * price + trade_cost(qty * price)["total"] > portfolio.cash:
                qty -= 1
            if qty > 0:
                cost = trade_cost(qty * price)["total"]
                portfolio.buy(dates.iloc[i + 1], s, price, qty, cost)

    last_prices = {s: float(closes[s].iloc[-1]) for s in symbols}
    portfolio.mark_to_market(dates.iloc[-1], last_prices)

    equity_curve = pd.DataFrame(portfolio.equity_curve)
    trade_log = pd.DataFrame(portfolio.trade_log)
    final_equity = equity_curve["equity"].iloc[-1] if not equity_curve.empty else starting_capital

    return PortfolioBacktestResult(
        portfolio=portfolio,
        equity_curve=equity_curve,
        trade_log=trade_log,
        final_equity=final_equity,
        rebalance_log=rebalance_log,
    )
