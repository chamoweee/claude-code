---
description: Run the fortnightly CMC Invest ETF buy workflow — confirm holdings, get fresh prices, allocate, audit, and record fills once Chamk confirms.
---

Run the fortnightly workflow end to end. Follow `CLAUDE.md` for all hard rules throughout — buys only, never react to news or drawdowns, flag drift rather than fixing it, general information only.

1. **Confirm holdings.** Show Chamk the current `data/holdings.csv` and `data/cash.json` and ask him to confirm they're still accurate (or correct them) before proceeding. Do not continue until he confirms.
2. **Fetch prices.** Invoke the `market-data` agent to fetch fresh ASX prices for A200, BGBL and VVLU into `data/prices.json`, with sources. If it cannot get a fresh, verified price for all three, stop and report why.
3. **Allocate.** Invoke the `allocator` agent to run `scripts/allocate.py` and draft `reports/YYYY-MM-DD-ticket.md`. If the script errors, stop and report the exact error — do not guess or patch around it.
4. **Audit.** Invoke the `compliance-auditor` agent to check the drafted ticket against the fortnightly checklist. If it FAILS, send it back to the allocator to fix, then re-audit. Repeat until PASS (or escalate to Chamk if it can't be resolved).
5. **Show Chamk the result.** Present, mobile-friendly:
   - The order table (ticker, units, limit, amount).
   - The compliance verdict (PASS + checklist highlights, or what was fixed).
   - Total spend, carry forward, and any drift alerts.
   - The placement steps (Limit order, Good for day, 10:15am–3:45pm Sydney).
6. **Wait.** Do not record anything yet. Wait for Chamk to place the orders himself in the CMC Invest app and come back with confirmed fills (from his contract note or told directly).
7. **Record fills.** Once Chamk confirms what actually filled (units, price, brokerage per order — fills may differ slightly from the ticket if a limit didn't fully execute), invoke the `ledger-keeper` agent to record them in `data/ledger.csv`, update `data/holdings.csv` and `data/cash.json`, and confirm back with a short summary.
