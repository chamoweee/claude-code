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
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")
    cfg, base = load_config(args.config)
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


if __name__ == "__main__":
    sys.exit(main())
