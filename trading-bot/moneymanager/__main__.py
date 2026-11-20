"""CLI: python -m moneymanager backtest config.example.json"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys

from .config import build_from_config, load_config
from .report import summarize


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="moneymanager", description="Multi-market trading money manager")
    sub = ap.add_subparsers(dest="cmd", required=True)
    bt = sub.add_parser("backtest", help="run a backtest / paper simulation from a config file")
    bt.add_argument("config")
    bt.add_argument("-v", "--verbose", action="store_true", help="log every fill/rejection")
    bt.add_argument("--equity-csv", help="write the equity curve to this CSV")
    bt.add_argument("--trades-csv", help="write all fills to this CSV")
    tr = sub.add_parser("trade", help="auto-trade on live data (paper broker unless --live)")
    tr.add_argument("config")
    tr.add_argument("--once", action="store_true", help="run a single cycle and exit (for cron)")
    tr.add_argument("--poll", type=float, help="seconds between cycles (default: a quarter of the timeframe)")
    tr.add_argument("--live", action="store_true",
                    help="allow the config's real-money broker (also needs MONEYMANAGER_LIVE=1)")
    tr.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(message)s" if args.cmd == "trade" else "%(message)s")
    cfg, base = load_config(args.config)
    if args.cmd == "trade":
        return trade(cfg, base, args)
    engine = build_from_config(cfg, base)
    pf = engine.run()
    mm = engine.mm

    stats = summarize(pf)
    print(json.dumps(stats, indent=2))
    print("\nExposure by asset class at end:",
          {k.value: round(v, 2) for k, v in pf.exposure_by_class().items()} or "flat")
    rejected = sum(1 for e in mm.events if e.kind == "rejected")
    resized = sum(1 for e in mm.events if e.kind == "resized")
    stops = sum(1 for e in mm.events if e.kind == "stop")
    print(f"Risk gate: {resized} orders resized, {rejected} rejected, {stops} stops hit")
    if mm.risk.halted:
        print(f"KILL SWITCH TRIPPED: {mm.risk.halt_reason}")

    if args.equity_csv:
        with open(args.equity_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "equity"])
            w.writerows(pf.equity_curve)
    if args.trades_csv:
        with open(args.trades_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "symbol", "side", "qty", "price", "commission", "reason"])
            for fl in pf.fills:
                w.writerow([fl.timestamp, fl.symbol, fl.side.value, fl.qty, fl.price, fl.commission, fl.reason])
    return 0


def trade(cfg: dict, base, args) -> int:
    from .live import build_autotrader

    engine = build_from_config(cfg, base, allow_live=args.live)
    if engine.mm.broker.is_live:
        print("*** LIVE TRADING WITH REAL MONEY ***")
    bot = build_autotrader(engine, cfg, base)
    if args.once:
        bot.cycle()
    else:
        bot.run_forever(args.poll)
    ai = engine.portfolio_strategy
    if ai is not None and hasattr(ai, "usage"):
        print(f"AI calls this run: {ai.calls}, tokens in/out: {ai.usage['input_tokens']}/{ai.usage['output_tokens']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
