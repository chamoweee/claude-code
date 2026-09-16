---
description: Run the paper-trading agent over your watchlist (init, run, or status)
---

## Your task

The user invoked `/trading-agent $ARGUMENTS`.

Parse `$ARGUMENTS` as `<action> [watchlist...]`, where `<action>` is one of:

- `init` — set up a new paper portfolio (optionally with a starting cash amount and a
  watchlist, e.g. `/trading-agent init 100000 AAPL MSFT BTC/USD`)
- `run` — fetch fresh data for the current watchlist, analyze it, and simulate trades
  (optionally pass symbols to add/override the watchlist for this run)
- `status` — just report current holdings, cash, and P&L without trading
- (no action, or anything else) — treat it as `run` with any given symbols

Load and follow the `trading-agent` skill to carry this out. It defines the portfolio
file format, the analysis workflow (including when to delegate to the `market-analyst`
subagent), risk limits, and the report format. Do not place any real orders or call any
brokerage/exchange execution API — this is a simulated paper-trading exercise only.
