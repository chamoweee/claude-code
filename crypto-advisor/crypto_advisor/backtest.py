"""Walk-forward backtest, built entirely from the price history already
fetched into `UniverseCoin.daily_prices` during a screen/advise run (no
extra network calls). At every rebalance date, only price data up to and
including that date is used -- no look-ahead.

Known, explicitly documented limitation: CoinGecko's free API cannot
reliably reconstruct which coins were in the investable universe (or their
fundamentals/classification) at each historical date, and cannot recover
delisted coins' history at all. This backtest therefore uses TODAY's
classification applied to each coin's historical prices, and a fixed,
currently-defined coin set -- it is a price/trend sanity check of the
signal logic, not a fully survivorship-bias-free simulation. See
report.md's data-quality section.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from .classify import CORE, REVENUE_GENERATING, Classification
from .logutil import get_logger
from .universe import UniverseCoin

logger = get_logger(__name__)

STARTING_CAPITAL_AUD = 10_000.0


def _price_series(coin: UniverseCoin) -> pd.Series:
    if not coin.daily_prices:
        return pd.Series(dtype=float)
    idx = pd.to_datetime([ts for ts, _ in coin.daily_prices], unit="ms").normalize()
    s = pd.Series([p for _, p in coin.daily_prices], index=idx)
    return s[~s.index.duplicated(keep="last")].sort_index()


def _build_price_panel(universe: list[UniverseCoin], coin_ids: list[str], start_date: str) -> pd.DataFrame:
    series = {}
    for coin in universe:
        if coin.coin_id in coin_ids:
            s = _price_series(coin)
            if not s.empty:
                series[coin.coin_id] = s
    if not series:
        return pd.DataFrame()
    panel = pd.DataFrame(series)
    panel = panel[panel.index >= pd.to_datetime(start_date)]
    return panel.sort_index()


def _equity_stats(equity: pd.Series, fee_bps_per_turnover: float, turnovers: list[float]) -> dict:
    if equity.empty or len(equity) < 2:
        return {"cagr_pct": None, "max_drawdown_pct": None, "volatility_pct": None,
                "win_rate_pct": None, "num_trades": len(turnovers), "total_costs_aud": None}
    days = (equity.index[-1] - equity.index[0]).days or 1
    years = days / 365.25
    total_return = equity.iloc[-1] / equity.iloc[0]
    cagr = (total_return ** (1 / years) - 1) * 100 if years > 0 and total_return > 0 else None

    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    max_dd = float(drawdown.min() * 100)

    daily_returns = equity.pct_change().dropna()
    vol = float(daily_returns.std() * np.sqrt(365) * 100) if len(daily_returns) > 5 else None

    period_returns = equity.resample("30D").last().pct_change().dropna()
    win_rate = float((period_returns > 0).mean() * 100) if len(period_returns) > 0 else None

    total_costs_aud = sum(turnovers) * fee_bps_per_turnover / 10_000 * STARTING_CAPITAL_AUD

    return {
        "cagr_pct": round(cagr, 2) if cagr is not None else None,
        "max_drawdown_pct": round(max_dd, 2),
        "volatility_pct": round(vol, 2) if vol is not None else None,
        "win_rate_pct": round(win_rate, 2) if win_rate is not None else None,
        "num_trades": len(turnovers),
        "total_costs_aud": round(total_costs_aud, 2),
    }


def _buy_and_hold(panel: pd.DataFrame, coin_id: str, fee_bps: float) -> tuple[pd.Series, list[float]]:
    if coin_id not in panel.columns:
        return pd.Series(dtype=float), []
    prices = panel[coin_id].dropna()
    if prices.empty:
        return pd.Series(dtype=float), []
    equity = prices / prices.iloc[0]
    return equity, [1.0]  # one entry "trade" (full turnover)


def _fixed_weight_rebalanced(panel: pd.DataFrame, weights: dict[str, float], rebalance_days: int) -> tuple[pd.Series, list[float]]:
    cols = [c for c in weights if c in panel.columns]
    if not cols:
        return pd.Series(dtype=float), []
    sub = panel[cols].dropna(how="all").ffill().dropna()
    if sub.empty:
        return pd.Series(dtype=float), []
    daily_returns = sub.pct_change().fillna(0)
    w = np.array([weights[c] for c in cols])
    w = w / w.sum()
    equity = [1.0]
    turnovers = []
    current_weights = w.copy()
    for i in range(1, len(sub)):
        period_return = float(np.dot(current_weights, daily_returns.iloc[i].values))
        equity.append(equity[-1] * (1 + period_return))
        drifted = current_weights * (1 + daily_returns.iloc[i].values)
        current_weights = drifted / drifted.sum() if drifted.sum() != 0 else current_weights
        if i % rebalance_days == 0:
            turnover = float(np.abs(current_weights - w).sum())
            turnovers.append(turnover)
            current_weights = w.copy()
    return pd.Series(equity, index=sub.index), turnovers


def _equal_weight_basket(panel: pd.DataFrame, coin_ids: list[str], rebalance_days: int) -> tuple[pd.Series, list[float]]:
    cols = [c for c in coin_ids if c in panel.columns]
    if not cols:
        return pd.Series(dtype=float), []
    weights = {c: 1.0 for c in cols}
    return _fixed_weight_rebalanced(panel, weights, rebalance_days)


def _sma(series: pd.Series, window: int, as_of_idx: int) -> Optional[float]:
    start = as_of_idx - window + 1
    if start < 0:
        return None
    return float(series.iloc[start:as_of_idx + 1].mean())


def _signal_rules_strategy(
    panel: pd.DataFrame,
    eligible_coin_ids: list[str],
    rebalance_days: int,
) -> tuple[pd.Series, list[float]]:
    """Simplified point-in-time trend strategy: at each rebalance date, equal-
    weight across eligible coins currently trading above both their 50- and
    200-day SMA (computed using only data up to that date); otherwise sit in
    cash (flat, 0% return) for that slice. This tests the trend/eligibility
    portion of signals.py -- the live system also weighs fundamentals and
    valuation using current data unavailable historically (see module
    docstring)."""
    cols = [c for c in eligible_coin_ids if c in panel.columns]
    if not cols:
        return pd.Series(dtype=float), []
    sub = panel[cols].dropna(how="all").ffill()
    if sub.empty or len(sub) < 210:
        return pd.Series(dtype=float), []
    daily_returns = sub.pct_change().fillna(0)

    equity = [1.0]
    turnovers = []
    held: set[str] = set()
    for i in range(1, len(sub)):
        if i >= 200 and (i % rebalance_days == 0 or i == 1):
            new_held = set()
            for c in cols:
                price_now = sub[c].iloc[i]
                sma50 = _sma(sub[c], 50, i)
                sma200 = _sma(sub[c], 200, i)
                if pd.notna(price_now) and sma50 and sma200 and price_now > sma50 and price_now > sma200:
                    new_held.add(c)
            if new_held != held:
                turnovers.append(1.0)
            held = new_held
        if held:
            period_return = float(daily_returns.iloc[i][list(held)].mean())
        else:
            period_return = 0.0
        equity.append(equity[-1] * (1 + period_return))
    return pd.Series(equity, index=sub.index), turnovers


def _naive_top_movers_strategy(panel: pd.DataFrame, coin_ids: list[str], rebalance_days: int, lookback_days: int) -> tuple[pd.Series, list[float]]:
    """Sanity check: buy whichever coin had the best return over the prior
    `lookback_days` at each rebalance, hold until the next rebalance."""
    cols = [c for c in coin_ids if c in panel.columns]
    if not cols:
        return pd.Series(dtype=float), []
    sub = panel[cols].dropna(how="all").ffill().dropna()
    if sub.empty or len(sub) < lookback_days + 2:
        return pd.Series(dtype=float), []
    daily_returns = sub.pct_change().fillna(0)
    equity = [1.0]
    turnovers = []
    current_pick = None
    for i in range(1, len(sub)):
        if i % rebalance_days == 0 or current_pick is None:
            lookback_start = max(0, i - lookback_days)
            past_returns = sub.iloc[i] / sub.iloc[lookback_start] - 1
            pick = past_returns.idxmax()
            if pick != current_pick:
                turnovers.append(1.0)
            current_pick = pick
        equity.append(equity[-1] * (1 + daily_returns.iloc[i][current_pick]))
    return pd.Series(equity, index=sub.index), turnovers


def run_backtest(universe: list[UniverseCoin], classifications: list[Classification], config: dict) -> dict:
    bcfg = config["backtest"]
    fee_bps = config["au_tax"]["exchange_fees_bps"]["default"]

    eligible_tiers = {CORE, REVENUE_GENERATING}
    class_by_id = {c.coin_id: c.tier for c in classifications}
    eligible_ids = [c.coin_id for c in universe if class_by_id.get(c.coin_id) in eligible_tiers]

    by_mcap = sorted(universe, key=lambda c: c.market_cap_aud or 0, reverse=True)
    basket_ids = [c.coin_id for c in by_mcap[: bcfg["benchmark_universe_cap"]]]

    all_ids = list({*basket_ids, *eligible_ids, "bitcoin", "ethereum"})
    panel = _build_price_panel(universe, all_ids, bcfg["start_date"])

    notes = [
        "Classification (core/revenue-generating/speculative) is applied using TODAY's data across the whole "
        "backtest period -- historical fundamentals/fees for each rebalance date aren't available on the free API.",
        "The coin universe used is today's top-market-cap set (capped at "
        f"{bcfg['benchmark_universe_cap']} coins); coins that were delisted/collapsed before today and would have "
        "been in a historical universe are not included -- this is a genuine survivorship-bias gap, not corrected.",
        f"Backtest window is limited by each coin's available CoinGecko history; BTC/ETH typically cover the full "
        f"{bcfg['start_date']} start, most alts cover less.",
    ]

    if panel.empty or "bitcoin" not in panel.columns:
        notes.append("No usable price panel (missing BTC history) -- backtest could not run.")
        return {"strategies": {}, "equity_curves": {}, "data_quality_notes": notes}

    strategies = {}
    curves = {}

    eq, tv = _buy_and_hold(panel, "bitcoin", fee_bps)
    strategies["buy_and_hold_btc"] = _equity_stats(eq, fee_bps, tv)
    curves["buy_and_hold_btc"] = list(zip(eq.index.strftime("%Y-%m-%d"), eq.values.tolist())) if not eq.empty else []

    eq, tv = _fixed_weight_rebalanced(panel, {"bitcoin": 0.7, "ethereum": 0.3}, bcfg["rebalance_days"])
    strategies["70_30_btc_eth"] = _equity_stats(eq, fee_bps, tv)
    curves["70_30_btc_eth"] = list(zip(eq.index.strftime("%Y-%m-%d"), eq.values.tolist())) if not eq.empty else []

    eq, tv = _equal_weight_basket(panel, basket_ids, bcfg["rebalance_days"])
    strategies["equal_weight_basket"] = _equity_stats(eq, fee_bps, tv)
    curves["equal_weight_basket"] = list(zip(eq.index.strftime("%Y-%m-%d"), eq.values.tolist())) if not eq.empty else []

    eq, tv = _signal_rules_strategy(panel, eligible_ids or basket_ids, bcfg["rebalance_days"])
    strategies["signal_rules"] = _equity_stats(eq, fee_bps, tv)
    curves["signal_rules"] = list(zip(eq.index.strftime("%Y-%m-%d"), eq.values.tolist())) if not eq.empty else []

    eq, tv = _naive_top_movers_strategy(panel, basket_ids, bcfg["rebalance_days"], bcfg["top_movers_lookback_days"])
    strategies["naive_top_movers"] = _equity_stats(eq, fee_bps, tv)
    curves["naive_top_movers"] = list(zip(eq.index.strftime("%Y-%m-%d"), eq.values.tolist())) if not eq.empty else []

    return {"strategies": strategies, "equity_curves": curves, "data_quality_notes": notes}
