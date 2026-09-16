#!/usr/bin/env python3
"""
Fortnightly ETF allocator for the CMC Invest assistant.

Reads config/portfolio.json, data/holdings.csv, data/prices.json and
data/cash.json, then proposes up to `max_etfs_per_fortnight` whole-unit
limit-buy orders that close the largest gaps to target allocation.

Stdlib only. Never invents prices or holdings — stops with an ERROR
message and a non-zero exit code if data is missing or stale.
"""
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "portfolio.json"
HOLDINGS_PATH = ROOT / "data" / "holdings.csv"
PRICES_PATH = ROOT / "data" / "prices.json"
CASH_PATH = ROOT / "data" / "cash.json"

MAX_PRICE_AGE_DAYS = 4


def error(msg: str):
    print(f"ERROR: {msg}")
    sys.exit(1)


def round_cents(x: float) -> float:
    return round(x + 1e-9, 2)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        error(f"missing config file {CONFIG_PATH}")
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    total_target = sum(s["target"] for s in config["sleeves"])
    if abs(total_target - 1.0) > 1e-6:
        error(f"sleeve targets sum to {total_target * 100:.2f}%, not 100%")
    return config


def load_holdings() -> dict:
    if not HOLDINGS_PATH.exists():
        error(f"missing holdings file {HOLDINGS_PATH}")
    holdings = {}
    with open(HOLDINGS_PATH, newline="") as f:
        for row in csv.DictReader(f):
            holdings[row["ticker"]] = {
                "units": float(row["units"]),
                "avg_cost": float(row["avg_cost"]),
            }
    return holdings


def load_prices():
    if not PRICES_PATH.exists():
        error(
            f"missing prices file {PRICES_PATH}. Run the market-data agent first."
        )
    with open(PRICES_PATH) as f:
        data = json.load(f)
    as_of_raw = data.get("as_of")
    if not as_of_raw:
        error("prices.json is missing an 'as_of' date")
    try:
        as_of = datetime.strptime(as_of_raw, "%Y-%m-%d").date()
    except ValueError:
        error(f"prices.json 'as_of' date '{as_of_raw}' is not in YYYY-MM-DD format")
    age_days = (date.today() - as_of).days
    if age_days > MAX_PRICE_AGE_DAYS:
        error(
            f"prices are {age_days} days old (as_of {as_of_raw}), "
            f"max allowed is {MAX_PRICE_AGE_DAYS} days. "
            "Run the market-data agent for fresh prices."
        )
    return data.get("prices", {}), as_of_raw


def load_cash() -> float:
    if not CASH_PATH.exists():
        error(f"missing cash file {CASH_PATH}")
    with open(CASH_PATH) as f:
        data = json.load(f)
    return float(data.get("carry_forward", 0))


def build_orders(chosen_sleeves, cash_pool, gaps, prices, max_order):
    """Split cash_pool across chosen_sleeves proportionally to positive gap."""
    weight_basis = {s["ticker"]: max(gaps[s["ticker"]], 0.0) for s in chosen_sleeves}
    basis_sum = sum(weight_basis.values())
    orders = {}
    for s in chosen_sleeves:
        t = s["ticker"]
        share = (weight_basis[t] / basis_sum) if basis_sum > 0 else (1.0 / len(chosen_sleeves))
        cash_i = cash_pool * share
        last = prices[t]
        limit = round_cents(last * (1 + LIMIT_BUFFER))
        units = int(cash_i // limit) if limit > 0 else 0
        amount = round_cents(units * limit)
        while amount > max_order and units > 0:
            units -= 1
            amount = round_cents(units * limit)
        orders[t] = {"ticker": t, "limit": limit, "units": units, "amount": amount}
    return orders


LIMIT_BUFFER = 0.002  # overwritten from config in main()


def main():
    global LIMIT_BUFFER
    config = load_config()
    holdings = load_holdings()
    prices, as_of = load_prices()
    carry_forward = load_cash()

    sleeves = config["sleeves"]
    for s in sleeves:
        if s["ticker"] not in prices:
            error(f"missing price for {s['ticker']}")

    contribution = float(config["contribution"])
    min_order = float(config["min_order"])
    max_order = float(config["max_order"])
    max_etfs = int(config["max_etfs_per_fortnight"])
    LIMIT_BUFFER = float(config["limit_buffer"])
    drift_alert_pp = float(config["drift_alert_pp"])

    current_value = {}
    for s in sleeves:
        t = s["ticker"]
        units = holdings.get(t, {}).get("units", 0.0)
        current_value[t] = units * prices[t]

    portfolio_value = sum(current_value.values())
    cash = round_cents(contribution + carry_forward)
    total = portfolio_value + cash

    gaps = {}
    for s in sleeves:
        t = s["ticker"]
        target_value = s["target"] * total
        gaps[t] = target_value - current_value[t]

    ranked = sorted(sleeves, key=lambda s: gaps[s["ticker"]], reverse=True)
    positive = [s for s in ranked if gaps[s["ticker"]] > 0]
    selected = positive[:max_etfs] if positive else ranked[:1]
    top_pick = selected[0]["ticker"]

    orders = build_orders(selected, cash, gaps, prices, max_order)

    if len(selected) > 1 and any(o["amount"] < min_order for o in orders.values()):
        selected = [next(s for s in sleeves if s["ticker"] == top_pick)]
        orders = build_orders(selected, cash, gaps, prices, max_order)

    # Use any rounding leftover to buy extra whole units of the top pick,
    # as long as it stays under max_order.
    spent = sum(o["amount"] for o in orders.values())
    leftover = round_cents(cash - spent)
    top_order = orders[top_pick]
    limit = top_order["limit"]
    while limit > 0 and leftover >= limit and round_cents(top_order["amount"] + limit) <= max_order:
        top_order["units"] += 1
        top_order["amount"] = round_cents(top_order["amount"] + limit)
        leftover = round_cents(leftover - limit)

    spent = round_cents(sum(o["amount"] for o in orders.values()))
    carry_forward_new = round_cents(cash - spent)

    new_total = round_cents(portfolio_value + spent)
    weights_before = {}
    weights_after = {}
    weights_target = {}
    for s in sleeves:
        t = s["ticker"]
        weights_target[t] = round_cents(s["target"] * 100)
        weights_before[t] = round_cents(current_value[t] / portfolio_value * 100) if portfolio_value > 0 else 0.0
        new_value_t = current_value[t] + orders.get(t, {}).get("amount", 0)
        weights_after[t] = round_cents(new_value_t / new_total * 100) if new_total > 0 else 0.0

    drift_alerts = []
    if portfolio_value > 5000:
        for s in sleeves:
            t = s["ticker"]
            diff = weights_before[t] - weights_target[t]
            if abs(diff) > drift_alert_pp:
                drift_alerts.append({
                    "ticker": t,
                    "weight_before_pp": weights_before[t],
                    "target_pp": weights_target[t],
                    "diff_pp": round_cents(diff),
                })

    result = {
        "as_of": as_of,
        "portfolio_value": round_cents(portfolio_value),
        "cash_available": cash,
        "orders": [
            {"ticker": t, "units": o["units"], "limit": o["limit"], "amount": o["amount"]}
            for t, o in orders.items() if o["units"] > 0
        ],
        "total_spend": spent,
        "carry_forward": carry_forward_new,
        "weights": {
            "before": weights_before,
            "after": weights_after,
            "target": weights_target,
        },
        "drift_alerts": drift_alerts,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
