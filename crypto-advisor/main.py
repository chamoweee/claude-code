#!/usr/bin/env python3
"""Crypto Screening & Advisory Agent -- CLI entry point.

    python main.py screen      # build the investable universe + screen.csv, no advisory
    python main.py advise      # full pipeline incl. BUY/ADD/HOLD/TRIM/SELL/WATCH actions
    python main.py simple      # condensed view: top movers/losers + BUY/ADD potentials -- prints to terminal
    python main.py backtest    # walk-forward backtest vs benchmarks
    python main.py live        # runs `advise` on a loop, with alerts + digests

Advisory only. Never connects to an exchange account with trading permissions;
public market data only. Signals are rule-based research output, not
financial advice.
"""
from __future__ import annotations

import argparse
import sys

from crypto_advisor.backtest import run_backtest
from crypto_advisor.config import load_config, load_env, load_portfolio
from crypto_advisor.logutil import get_logger
from crypto_advisor.report import OUTPUT_DIR, generate_all_reports
from crypto_advisor.scheduler import run_live_loop, run_once_and_report, run_pipeline_once

logger = get_logger("main")


def cmd_screen(args) -> None:
    config = load_config()
    env = load_env()
    portfolio = load_portfolio()
    ctx = run_once_and_report(config, env, portfolio, include_advisory=False)
    print(f"Screened {len(ctx.universe)} coins. See output/screen.csv, output/live_report.html, output/report.md")


def cmd_simple(args) -> None:
    """The condensed on-demand view: top movers/losers past a threshold, and
    BUY/ADD potentials with a real historical weekly-return range. Runs the
    full advisory pipeline (same as `advise`) then prints output/simple_report.md."""
    config = load_config()
    env = load_env()
    portfolio = load_portfolio()
    ctx = run_once_and_report(config, env, portfolio, include_advisory=True)
    print((OUTPUT_DIR / "simple_report.md").read_text())
    if ctx.stale_sources:
        print(f"\nWARNING: stale/failed data sources this run: {ctx.stale_sources}")


def cmd_advise(args) -> None:
    config = load_config()
    env = load_env()
    portfolio = load_portfolio()
    ctx = run_once_and_report(config, env, portfolio, include_advisory=True)
    print(f"Advised on {len(ctx.final_actions)} coins. See output/actions.md, output/live_report.html")
    if ctx.stale_sources:
        print(f"WARNING: stale/failed data sources this run: {ctx.stale_sources}")


def cmd_backtest(args) -> None:
    config = load_config()
    env = load_env()
    portfolio = load_portfolio()
    ctx = run_pipeline_once(config, env, portfolio, include_advisory=False)
    print(f"Running backtest over {len(ctx.universe)} coins from {config['backtest']['start_date']}...")
    results = run_backtest(ctx.universe, ctx.classifications, config)
    ctx.backtest_results = results
    generate_all_reports(ctx)
    for name, stats in results["strategies"].items():
        print(f"{name}: CAGR {stats.get('cagr_pct')}%, max DD {stats.get('max_drawdown_pct')}%, "
              f"vol {stats.get('volatility_pct')}%, win rate {stats.get('win_rate_pct')}%, "
              f"trades {stats.get('num_trades')}, costs A${stats.get('total_costs_aud')}")
    print("Full results in output/report.md and output/charts/backtest_equity_curves.png")


def cmd_live(args) -> None:
    config = load_config()
    env = load_env()
    portfolio = load_portfolio()
    max_iterations = args.iterations
    print(f"Starting live loop (refresh every {config['general']['refresh_interval_seconds']}s"
          f"{f', max {max_iterations} iterations' if max_iterations else ''}). Ctrl+C to stop.")
    try:
        run_live_loop(config, env, portfolio, max_iterations=max_iterations)
    except KeyboardInterrupt:
        print("Stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crypto Screening & Advisory Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("screen", help="Build the investable universe and screen.csv").set_defaults(func=cmd_screen)
    sub.add_parser("advise", help="Full pipeline with BUY/ADD/HOLD/TRIM/SELL/WATCH actions").set_defaults(func=cmd_advise)
    sub.add_parser("simple", help="Condensed on-demand view: top movers/losers + BUY/ADD potentials").set_defaults(func=cmd_simple)
    sub.add_parser("backtest", help="Walk-forward backtest vs benchmarks").set_defaults(func=cmd_backtest)

    live_parser = sub.add_parser("live", help="Run the live loop (Ctrl+C to stop)")
    live_parser.add_argument("--iterations", type=int, default=None, help="Stop after N cycles (for testing)")
    live_parser.set_defaults(func=cmd_live)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
