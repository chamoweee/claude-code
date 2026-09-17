"""Renders every output artifact: screen.csv, live_report.html, actions.md,
report.md, charts/, plus signals_history.csv and the dashboard's state.json.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from jinja2 import Environment, FileSystemLoader

from .classify import CORE, REVENUE_GENERATING, SPECULATIVE, Classification
from .config import PROJECT_ROOT, Portfolio
from .insights import Insight
from .logutil import get_logger
from .metrics import CoinMetrics, historical_weekly_return_range
from .risk import FinalAction
from .signals import ADD, BUY
from .universe import UniverseCoin

logger = get_logger(__name__)

OUTPUT_DIR = PROJECT_ROOT / "output"
CHARTS_DIR = OUTPUT_DIR / "charts"
DATA_DIR = PROJECT_ROOT / "data"
TEMPLATES_DIR = Path(__file__).parent / "templates"
SIGNALS_HISTORY_PATH = DATA_DIR / "signals_history.csv"
SIGNALS_HISTORY_HEADER = ["timestamp", "coin_id", "action", "confidence", "score", "price_aud", "classification", "top_reason"]

ACTION_PRIORITY = {"SELL": 0, "TRIM": 1, "BUY": 2, "ADD": 3, "HOLD": 4, "WATCH": 5}


@dataclass
class ReportContext:
    universe: list[UniverseCoin]
    metrics_by_id: dict[str, CoinMetrics]
    classifications: list[Classification]
    movers: dict
    insights: list[Insight]
    global_data: Optional[dict]
    categories: list[dict]
    final_actions: list[FinalAction]
    portfolio: Portfolio
    summary_text: Optional[str]
    fetch_time: datetime
    stale_sources: list[str]
    config: dict
    weights_by_id: dict[str, float] = field(default_factory=dict)
    total_value_aud: float = 0.0
    core_pct: float = 0.0
    speculative_pct: float = 0.0
    backtest_results: Optional[dict] = None
    # {coin_id: (usd_price, is_stale)} from the Binance WS stream, holdings/watchlist only.
    # Informational only -- signals/risk always use the REST-derived AUD price above.
    ws_prices: dict[str, tuple[float, bool]] = field(default_factory=dict)


# --------------------------------------------------------------------------- screen.csv

def write_screen_csv(ctx: ReportContext) -> Path:
    classification_by_id = {c.coin_id: c for c in ctx.classifications}
    rows = []
    for coin in ctx.universe:
        m = ctx.metrics_by_id.get(coin.coin_id)
        cls = classification_by_id.get(coin.coin_id)
        rows.append({
            "coin_id": coin.coin_id, "symbol": coin.symbol, "name": coin.name,
            "classification": cls.tier if cls else None,
            "price_aud": coin.price_aud, "market_cap_aud": coin.market_cap_aud,
            "fdv_aud": m.fully_diluted_valuation_aud if m else None,
            "supply_ratio": m.supply_ratio if m else None,
            "annual_supply_inflation_pct": m.annual_supply_inflation_pct if m else None,
            "unlock_risk_flag": m.unlock_risk_flag if m else None,
            "avg_volume_30d_aud": m.avg_volume_30d_aud if m else None,
            "avg_volume_90d_aud": m.avg_volume_90d_aud if m else None,
            "volume_to_mcap_ratio": m.volume_to_mcap_ratio if m else None,
            "fees_ttm_usd": m.fees_ttm_usd if m else None,
            "revenue_ttm_usd": m.revenue_ttm_usd if m else None,
            "revenue_quarters_present": m.revenue_quarters_present if m else None,
            "price_to_fees": m.price_to_fees if m else None,
            "price_to_revenue": m.price_to_revenue if m else None,
            "volatility_30d_pct": m.volatility_30d_annualized_pct if m else None,
            "volatility_90d_pct": m.volatility_90d_annualized_pct if m else None,
            "volatility_365d_pct": m.volatility_365d_annualized_pct if m else None,
            "max_drawdown_pct": m.max_drawdown_pct if m else None,
            "days_since_ath": m.days_since_ath if m else None,
            "pct_below_ath": m.pct_below_ath if m else None,
            "correlation_to_btc_2y": m.correlation_to_btc_2y if m else None,
            "beta_to_btc_2y": m.beta_to_btc_2y if m else None,
            "top_exchange_volume_share_pct": m.top_exchange_volume_share_pct if m else None,
            "exchange_concentration_flag": m.exchange_concentration_flag if m else None,
            "price_change_1h_pct": coin.price_change_pct_1h,
            "price_change_24h_pct": coin.price_change_pct_24h,
            "price_change_7d_pct": coin.price_change_pct_7d,
            "price_history_days": coin.price_history_days,
            "listed_exchanges": ";".join(coin.listed_exchanges),
            "ccxt_exchange": m.ccxt_exchange if m else None,
            "ccxt_avg_volume_30d_usd": m.ccxt_avg_volume_30d_usd if m else None,
            "ccxt_volume_cross_check": m.ccxt_volume_cross_check if m else None,
        })
    df = pd.DataFrame(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "screen.csv"
    df.to_csv(path, index=False)
    return path


# --------------------------------------------------------------------------- signals history

def append_signals_history(ctx: ReportContext) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    classification_by_id = {c.coin_id: c for c in ctx.classifications}
    is_new = not SIGNALS_HISTORY_PATH.exists()
    with open(SIGNALS_HISTORY_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SIGNALS_HISTORY_HEADER)
        if is_new:
            writer.writeheader()
        for a in ctx.final_actions:
            cls = classification_by_id.get(a.coin_id)
            writer.writerow({
                "timestamp": ctx.fetch_time.isoformat(),
                "coin_id": a.coin_id,
                "action": a.action,
                "confidence": a.confidence,
                "score": a.score,
                "price_aud": a.entry_price_aud,
                "classification": cls.tier if cls else None,
                "top_reason": a.reasons[0] if a.reasons else "",
            })


def read_previous_actions() -> dict[str, dict]:
    """Last recorded action per coin, read BEFORE this run's rows are appended."""
    if not SIGNALS_HISTORY_PATH.exists():
        return {}
    df = pd.read_csv(SIGNALS_HISTORY_PATH)
    if df.empty:
        return {}
    latest = df.sort_values("timestamp").groupby("coin_id").tail(1)
    return {row["coin_id"]: row.to_dict() for _, row in latest.iterrows()}


def read_previous_classifications() -> dict[str, str]:
    prev = read_previous_actions()
    return {cid: row.get("classification") for cid, row in prev.items() if row.get("classification")}


# --------------------------------------------------------------------------- actions.md

def bull_bear_points(coin: UniverseCoin, m: Optional[CoinMetrics], cls: Optional[Classification]) -> tuple[list[str], list[str]]:
    bull, bear = [], []
    if not m:
        return bull, bear
    if cls and cls.tier in (CORE, REVENUE_GENERATING):
        bull.append(f"classified {cls.tier}")
    if m.sma_50 and coin.price_aud and coin.price_aud > m.sma_50:
        bull.append(f"trading above its 50d SMA (A${coin.price_aud:,.4f} > A${m.sma_50:,.4f})")
    if m.pct_below_ath is not None and abs(m.pct_below_ath) <= 5:
        bull.append(f"within {abs(m.pct_below_ath):.1f}% of all-time high")
    if m.revenue_quarters_present and m.revenue_quarters_present >= 6:
        bull.append(f"revenue in {m.revenue_quarters_present}/8 trailing quarters")

    if cls and cls.tier == SPECULATIVE:
        bear.append("classified speculative -- not eligible for BUY/ADD")
    if m.annual_supply_inflation_pct is not None and m.annual_supply_inflation_pct > 10:
        bear.append(f"high annual supply inflation ({m.annual_supply_inflation_pct:.1f}%)")
    if m.unlock_risk_flag:
        bear.append("large token unlock flagged within 30 days")
    if m.max_drawdown_pct is not None and m.max_drawdown_pct < -70:
        bear.append(f"max drawdown {m.max_drawdown_pct:.1f}% over available history")
    if m.exchange_concentration_flag:
        bear.append(f"volume concentrated on one exchange ({m.top_exchange_volume_share_pct:.1f}%)")
    return bull, bear


def write_actions_md(ctx: ReportContext, previous_actions: dict[str, dict]) -> Path:
    lines = [f"# Actions -- {ctx.fetch_time.isoformat()}", "",
             "_Rule-based research output. Not financial advice._", ""]

    lines.append("## Today's actions")
    lines.append("")
    lines.append("| Coin | Action | Confidence | Score | Suggested | Entry | Stop |")
    lines.append("|---|---|---|---|---|---|---|")
    ordered = sorted(ctx.final_actions, key=lambda a: ACTION_PRIORITY.get(a.action, 9))
    for a in ordered:
        suggested = f"A${a.suggested_aud:,.2f}" if a.suggested_aud else "-"
        entry = f"A${a.entry_price_aud:,.4f}" if a.entry_price_aud else "-"
        stop = f"A${a.stop_price_aud:,.4f}" if a.stop_price_aud else "-"
        lines.append(f"| {a.coin_id} | **{a.action}** | {a.confidence} | {a.score:.2f} | {suggested} | {entry} | {stop} |")

    lines.append("")
    lines.append("## Reasons per coin")
    for a in ordered:
        lines.append(f"\n### {a.coin_id} -- {a.action} ({a.confidence} confidence, score {a.score:.2f})")
        for r in a.reasons:
            lines.append(f"- {r}")
        if a.tax_disclaimer:
            lines.append(f"- {a.tax_disclaimer}")

    lines.append("\n## Allocation summary")
    lines.append(f"- Total portfolio value: A${ctx.total_value_aud:,.2f}")
    lines.append(f"- Cash available: A${ctx.portfolio.cash_aud:,.2f}")
    lines.append(f"- Core allocation: {ctx.core_pct:.1f}% (min target {ctx.config['risk']['min_core_allocation_pct']}%)")
    lines.append(f"- Speculative allocation: {ctx.speculative_pct:.1f}% (cap {ctx.config['risk']['max_total_speculative_allocation_pct']}%)")
    for cid, w in sorted(ctx.weights_by_id.items(), key=lambda kv: -kv[1]):
        lines.append(f"  - {cid}: {w:.1f}% of portfolio")

    lines.append("\n## Changes since last run")
    changed = False
    for a in ordered:
        prev = previous_actions.get(a.coin_id)
        prev_action = prev.get("action") if prev else None
        if prev_action and prev_action != a.action:
            changed = True
            lines.append(f"- {a.coin_id}: {prev_action} -> **{a.action}**")
        elif not prev:
            changed = True
            lines.append(f"- {a.coin_id}: new (no prior record) -> **{a.action}**")
    if not changed:
        lines.append("- No action changes since the last run.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "actions.md"
    path.write_text("\n".join(lines))
    return path


# --------------------------------------------------------------------------- report.md

def write_report_md(ctx: ReportContext) -> Path:
    lines = [f"# Report -- {ctx.fetch_time.isoformat()}", "",
             "_Rule-based research output. Not financial advice._", ""]

    classification_by_id = {c.coin_id: c for c in ctx.classifications}

    if ctx.backtest_results:
        lines.append("## Backtest comparison")
        lines.append("")
        lines.append("| Strategy | CAGR | Max drawdown | Volatility | Win rate | Trades | Costs |")
        lines.append("|---|---|---|---|---|---|---|")
        for name, r in ctx.backtest_results.get("strategies", {}).items():
            lines.append(f"| {name} | {r.get('cagr_pct', 'N/A')}% | {r.get('max_drawdown_pct', 'N/A')}% | "
                          f"{r.get('volatility_pct', 'N/A')}% | {r.get('win_rate_pct', 'N/A')}% | "
                          f"{r.get('num_trades', 'N/A')} | A${r.get('total_costs_aud', 0):,.2f} |")
        if ctx.backtest_results.get("data_quality_notes"):
            lines.append("\n**Data-quality notes:**")
            for note in ctx.backtest_results["data_quality_notes"]:
                lines.append(f"- {note}")
    else:
        lines.append("## Backtest comparison")
        lines.append("\n_Run `python main.py backtest` to populate this section._")

    lines.append("\n## Bull / bear per coin")
    for coin in ctx.universe:
        m = ctx.metrics_by_id.get(coin.coin_id)
        cls = classification_by_id.get(coin.coin_id)
        bull, bear = bull_bear_points(coin, m, cls)
        lines.append(f"\n### {coin.symbol.upper()} ({coin.coin_id}) -- {cls.tier if cls else 'unclassified'}")
        lines.append("**Bull:** " + ("; ".join(bull) if bull else "no notable bull points from available data"))
        lines.append("**Bear:** " + ("; ".join(bear) if bear else "no notable bear points from available data"))

    lines.append("\n## Excluded-coin summary")
    excluded_path = DATA_DIR / "excluded_coins_log.csv"
    if excluded_path.exists():
        df = pd.read_csv(excluded_path)
        df["reason_group"] = df["reason"].str.split(":").str[0]
        counts = df.groupby("reason_group").size().sort_values(ascending=False)
        lines.append(f"\nTotal exclusion events logged: {len(df)} (this run appends to a running log)")
        lines.append("\n| Reason | Count |")
        lines.append("|---|---|")
        for reason, count in counts.items():
            lines.append(f"| {reason} | {count} |")
    else:
        lines.append("\n_No exclusions logged yet._")

    lines.append("\n## Data-quality section")
    quality_path = DATA_DIR / "data_quality_log.csv"
    if quality_path.exists():
        df = pd.read_csv(quality_path)
        counts = df.groupby(["source", "field"]).size().sort_values(ascending=False).head(25)
        lines.append(f"\nTotal data-quality events logged: {len(df)}")
        lines.append("\n| Source | Field | Count |")
        lines.append("|---|---|---|")
        for (source, field_name), count in counts.items():
            lines.append(f"| {source} | {field_name} | {count} |")
    else:
        lines.append("\n_No data-quality issues logged yet._")

    lines.append("\n### Known limitations")
    lines.append("- Historical circulating supply and token-unlock schedules are only available for some coins on "
                 "free data sources; genuinely N/A for the rest, never estimated.")
    lines.append("- True survivorship-bias-free backtesting (including delisted coins) is not possible on free "
                 "CoinGecko data -- the backtest uses coins with available historical data only.")
    lines.append("- DefiLlama protocol-to-coin mapping (config.yaml `defillama_slug_map`) is maintained but "
                 "inherently incomplete; unmapped coins show fees/revenue as N/A.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "report.md"
    path.write_text("\n".join(lines))
    return path


# --------------------------------------------------------------------------- charts

def _classification_colors(classifications: list[Classification]) -> dict[str, str]:
    palette = {CORE: "#4caf50", REVENUE_GENERATING: "#42a5f5", SPECULATIVE: "#ef5350"}
    return {c.coin_id: palette.get(c.tier, "#999") for c in classifications}


def chart_movers_heatmap(movers: dict, path: Path) -> Optional[Path]:
    rows = (movers.get("24h", {}).get("gainers", []) + movers.get("24h", {}).get("losers", []))
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: r.pct_change)
    fig, ax = plt.subplots(figsize=(8, max(3, len(rows) * 0.35)))
    colors = ["#4caf50" if r.pct_change >= 0 else "#ef5350" for r in rows]
    ax.barh([r.symbol for r in rows], [r.pct_change for r in rows], color=colors)
    ax.set_xlabel("24h % change")
    ax.set_title("Top movers (24h)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_sector_performance(categories: list[dict], path: Path) -> Optional[Path]:
    ranked = [c for c in categories if c.get("market_cap_change_24h") is not None]
    if not ranked:
        return None
    ranked.sort(key=lambda c: c["market_cap_change_24h"])
    ranked = ranked[:10] + ranked[-10:] if len(ranked) > 20 else ranked
    fig, ax = plt.subplots(figsize=(8, max(3, len(ranked) * 0.3)))
    colors = ["#4caf50" if c["market_cap_change_24h"] >= 0 else "#ef5350" for c in ranked]
    ax.barh([c["name"] for c in ranked], [c["market_cap_change_24h"] for c in ranked], color=colors)
    ax.set_xlabel("24h market cap % change")
    ax.set_title("Sector performance")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_drawdown_volatility(universe: list[UniverseCoin], metrics_by_id: dict, path: Path) -> Optional[Path]:
    data = [(c.symbol.upper(), metrics_by_id[c.coin_id].max_drawdown_pct, metrics_by_id[c.coin_id].volatility_365d_annualized_pct)
            for c in universe if c.coin_id in metrics_by_id
            and metrics_by_id[c.coin_id].max_drawdown_pct is not None
            and metrics_by_id[c.coin_id].volatility_365d_annualized_pct is not None]
    if not data:
        return None
    data.sort(key=lambda x: x[1])
    data = data[:25]
    symbols, drawdowns, vols = zip(*data)
    fig, ax1 = plt.subplots(figsize=(10, max(3, len(symbols) * 0.3)))
    x = range(len(symbols))
    ax1.barh(x, drawdowns, color="#ef5350", alpha=0.7, label="Max drawdown %")
    ax1.set_yticks(list(x))
    ax1.set_yticklabels(symbols)
    ax1.set_xlabel("Max drawdown %")
    ax2 = ax1.twiny()
    ax2.plot(vols, x, "o", color="#ffb454", label="365d volatility %")
    ax2.set_xlabel("365d annualised volatility %")
    fig.suptitle("Drawdown vs volatility")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_btc_beta_scatter(universe: list[UniverseCoin], metrics_by_id: dict, classifications: list[Classification], path: Path) -> Optional[Path]:
    colors_by_id = _classification_colors(classifications)
    xs, ys, colors, labels = [], [], [], []
    for c in universe:
        m = metrics_by_id.get(c.coin_id)
        if not m or m.beta_to_btc_2y is None or m.volatility_365d_annualized_pct is None:
            continue
        xs.append(m.beta_to_btc_2y)
        ys.append(m.volatility_365d_annualized_pct)
        colors.append(colors_by_id.get(c.coin_id, "#999"))
        labels.append(c.symbol.upper())
    if not xs:
        return None
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(xs, ys, c=colors)
    for x, y, label in zip(xs, ys, labels):
        ax.annotate(label, (x, y), fontsize=7, alpha=0.8)
    ax.set_xlabel("Beta to BTC (2y)")
    ax.set_ylabel("365d annualised volatility %")
    ax.set_title("BTC-beta vs volatility (green=core, blue=revenue-generating, red=speculative)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_backtest_equity_curves(backtest_results: Optional[dict], path: Path) -> Optional[Path]:
    if not backtest_results or "equity_curves" not in backtest_results:
        return None
    fig, ax = plt.subplots(figsize=(9, 5))
    for name, curve in backtest_results["equity_curves"].items():
        if not curve:
            continue
        dates, values = zip(*curve)
        ax.plot(dates, values, label=name)
    ax.set_ylabel("Equity (normalised to 1.0)")
    ax.set_title("Backtest equity curves")
    ax.legend(fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def generate_charts(ctx: ReportContext) -> list[Path]:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    outputs = []
    for fn, filename, args in [
        (chart_movers_heatmap, "movers_heatmap.png", (ctx.movers,)),
        (chart_sector_performance, "sector_performance.png", (ctx.categories,)),
        (chart_drawdown_volatility, "drawdown_volatility.png", (ctx.universe, ctx.metrics_by_id)),
        (chart_btc_beta_scatter, "btc_beta_scatter.png", (ctx.universe, ctx.metrics_by_id, ctx.classifications)),
        (chart_backtest_equity_curves, "backtest_equity_curves.png", (ctx.backtest_results,)),
    ]:
        try:
            result = fn(*args, CHARTS_DIR / filename)
            if result:
                outputs.append(result)
        except Exception as exc:  # noqa: BLE001 - a chart failure should never crash the pipeline
            logger.warning("chart generation failed for %s: %s", filename, exc)
    return outputs


# --------------------------------------------------------------------------- live_report.html + state.json

def _overview_dict(ctx: ReportContext) -> dict:
    btc = next((c for c in ctx.universe if c.coin_id == "bitcoin"), None)
    eth = next((c for c in ctx.universe if c.coin_id == "ethereum"), None)
    gd = ctx.global_data or {}
    total_mcap = (gd.get("total_market_cap") or {}).get(ctx.config["general"]["vs_currency"])
    total_mcap_chg = gd.get("market_cap_change_percentage_24h_usd")
    dominance = (gd.get("market_cap_percentage") or {}).get("btc")
    n = len(ctx.universe) or 1
    up_24h = sum(1 for c in ctx.universe if (c.price_change_pct_24h or 0) > 0)
    up_7d = sum(1 for c in ctx.universe if (c.price_change_pct_7d or 0) > 0)
    return {
        "total_mcap": f"A${total_mcap:,.0f}" if total_mcap else "N/A",
        "total_mcap_chg": f"{total_mcap_chg:+.2f}%" if total_mcap_chg is not None else "N/A",
        "btc_price": f"A${btc.price_aud:,.0f}" if btc and btc.price_aud else "N/A",
        "btc_chg": f"{btc.price_change_pct_24h:+.2f}%" if btc and btc.price_change_pct_24h is not None else "N/A",
        "eth_price": f"A${eth.price_aud:,.0f}" if eth and eth.price_aud else "N/A",
        "eth_chg": f"{eth.price_change_pct_24h:+.2f}%" if eth and eth.price_change_pct_24h is not None else "N/A",
        "btc_dominance": f"{dominance:.1f}%" if dominance is not None else "N/A",
        "breadth_24h": f"{up_24h}/{n} up",
        "breadth_7d": f"{up_7d}/{n} up",
    }


def write_live_report_html(ctx: ReportContext) -> Path:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("live_report.html.j2")

    actions_for_template = []
    for a in sorted(ctx.final_actions, key=lambda a: ACTION_PRIORITY.get(a.action, 9)):
        actions_for_template.append({
            "coin_id": a.coin_id, "action": a.action, "confidence": a.confidence, "score": a.score,
            "suggested_aud": a.suggested_aud, "entry_price_aud": a.entry_price_aud, "stop_price_aud": a.stop_price_aud,
            "top_reason": a.reasons[0] if a.reasons else "",
        })

    html = template.render(
        fetch_time=ctx.fetch_time.strftime("%Y-%m-%d %H:%M:%S"),
        stale_sources=ctx.stale_sources,
        overview=_overview_dict(ctx),
        summary_text=ctx.summary_text,
        insights=ctx.insights,
        actions=actions_for_template,
        movers=ctx.movers,
        categories=sorted(ctx.categories, key=lambda c: -(c.get("market_cap_change_24h") or -999)),
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "live_report.html"
    path.write_text(html)
    return path


def write_state_json(ctx: ReportContext) -> Path:
    """Compact JSON snapshot the Streamlit dashboard reads, so it doesn't need
    to recompute the whole pipeline on every auto-refresh."""
    classification_by_id = {c.coin_id: c for c in ctx.classifications}

    def mover_row(r):
        return {"symbol": r.symbol, "price_aud": r.price_aud, "pct_change": r.pct_change,
                "volume_24h_aud": r.volume_24h_aud, "volume_vs_30d_avg": r.volume_vs_30d_avg,
                "market_cap_aud": r.market_cap_aud, "classification": r.classification, "held": r.held}

    state = {
        "fetch_time": ctx.fetch_time.isoformat(),
        "stale_sources": ctx.stale_sources,
        "overview": _overview_dict(ctx),
        "summary_text": ctx.summary_text,
        "insights": [{"rule": i.rule, "message": i.message, "importance": i.importance, "coin_id": i.coin_id} for i in ctx.insights],
        "actions": [{
            "coin_id": a.coin_id, "action": a.action, "confidence": a.confidence, "score": a.score,
            "suggested_aud": a.suggested_aud, "suggested_units": a.suggested_units,
            "entry_price_aud": a.entry_price_aud, "stop_price_aud": a.stop_price_aud,
            "reasons": a.reasons, "held": a.held,
        } for a in ctx.final_actions],
        "movers": {tf: {k: [mover_row(r) for r in v] for k, v in tables.items()} for tf, tables in ctx.movers.items()},
        "allocation": {"total_value_aud": ctx.total_value_aud, "cash_aud": ctx.portfolio.cash_aud,
                       "core_pct": ctx.core_pct, "speculative_pct": ctx.speculative_pct,
                       "weights_by_id": ctx.weights_by_id},
        "ws_prices": {cid: {"usd_price": p, "stale": stale} for cid, (p, stale) in ctx.ws_prices.items()},
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "state.json"
    path.write_text(json.dumps(state, default=str, indent=2))
    return path


def _range_str(rng: Optional[dict]) -> str:
    if not rng:
        return "not enough price history"
    return f"{rng['p10']:+.1f}% to {rng['p90']:+.1f}% (median {rng['median']:+.1f}%, over {rng['samples']} weeks)"


def write_simple_report(ctx: ReportContext) -> Path:
    """The condensed, on-demand view: top movers beyond a threshold, top
    losers beyond a threshold, and the best-scoring BUY/ADD-eligible coins
    (or the closest candidates, if none currently qualify) -- each with a
    real historical weekly-return range instead of a fabricated forecast.
    Written fresh every time `python main.py simple` (or `live`) runs."""
    scfg = ctx.config["simple_report"]
    threshold = scfg["mover_threshold_pct"]
    top_n = scfg["top_n"]
    coin_by_id = {c.coin_id: c for c in ctx.universe}

    movers_24h = ctx.movers.get("24h", {})
    tagged_moves = (
        [(r, False) for r in movers_24h.get("gainers", [])]
        + [(r, True) for r in movers_24h.get("high_risk_gainers", [])]
        + [(r, False) for r in movers_24h.get("losers", [])]
        + [(r, True) for r in movers_24h.get("high_risk_losers", [])]
    )
    seen_ids = set()
    deduped = []  # [(row, is_high_risk), ...]
    for r, is_high_risk in sorted(tagged_moves, key=lambda pair: pair[0].pct_change, reverse=True):
        if r.coin_id in seen_ids:
            continue
        seen_ids.add(r.coin_id)
        deduped.append((r, is_high_risk))

    gainers = [pair for pair in deduped if pair[0].pct_change >= threshold][:top_n]
    losers = sorted([pair for pair in deduped if pair[0].pct_change <= -threshold],
                     key=lambda pair: pair[0].pct_change)[:top_n]

    lines = [f"# Quick Report -- {ctx.fetch_time.strftime('%Y-%m-%d %H:%M UTC')}", "",
             "_Rule-based research output. Not financial advice._", ""]

    lines.append(f"## Top movers (>{threshold:.0f}%, 24h)")
    if gainers:
        for r, is_high_risk in gainers:
            risk_tag = " *(thin liquidity -- high risk)*" if is_high_risk else ""
            lines.append(f"- **{r.symbol} {r.pct_change:+.1f}%** -- A${r.price_aud:,.4f}{risk_tag}")
    else:
        lines.append(f"- None moved more than +{threshold:.0f}% in the last 24h.")

    lines.append(f"\n## Top losers (<-{threshold:.0f}%, 24h)")
    if losers:
        for r, is_high_risk in losers:
            risk_tag = " *(thin liquidity -- high risk)*" if is_high_risk else ""
            lines.append(f"- **{r.symbol} {r.pct_change:+.1f}%** -- A${r.price_aud:,.4f}{risk_tag}")
    else:
        lines.append(f"- None dropped more than -{threshold:.0f}% in the last 24h.")

    lines.append("\n## Potentials")
    ranked = sorted(ctx.final_actions, key=lambda a: a.score, reverse=True)
    buy_eligible = [a for a in ranked if a.action in (BUY, ADD)][:top_n]
    if buy_eligible:
        lines.append(f"\n**{len(buy_eligible)} coin(s) currently clear the bar for {BUY}/{ADD}:**\n")
        for a in buy_eligible:
            coin = coin_by_id.get(a.coin_id)
            rng = historical_weekly_return_range([p for _, p in coin.daily_prices]) if coin else None
            lines.append(f"- **{a.coin_id}** -- {a.action} (score {a.score:.2f}, {a.confidence} confidence). "
                         f"Typical 1-week range: {_range_str(rng)}.")
    else:
        lines.append("\nNo coin currently clears the bar for BUY/ADD "
                     "(only core/revenue-generating coins are eligible, and none scored high enough this run). "
                     f"Closest {top_n} by score:\n")
        closest = [a for a in ranked if a.action not in ("SELL", "TRIM")][:top_n]
        for a in closest:
            coin = coin_by_id.get(a.coin_id)
            rng = historical_weekly_return_range([p for _, p in coin.daily_prices]) if coin else None
            lines.append(f"- **{a.coin_id}** -- {a.action} (score {a.score:.2f}, {a.confidence} confidence). "
                         f"Typical 1-week range: {_range_str(rng)}.")

    lines.append("\n---")
    lines.append("_\"Typical 1-week range\" is the real 10th-90th percentile of this coin's trailing 7-day "
                 "returns over its available price history -- what it has actually done, not a prediction "
                 "of what it will do next. A big mover above never triggers a BUY on its own._")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "simple_report.md"
    path.write_text("\n".join(lines))
    return path


def generate_all_reports(ctx: ReportContext) -> None:
    previous_actions = read_previous_actions()
    write_screen_csv(ctx)
    write_actions_md(ctx, previous_actions)
    write_report_md(ctx)
    write_simple_report(ctx)
    write_live_report_html(ctx)
    write_state_json(ctx)
    generate_charts(ctx)
    append_signals_history(ctx)
    logger.info("All reports written to %s", OUTPUT_DIR)
