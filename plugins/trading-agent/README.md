# Trading Agent

A **paper-trading** research agent for stocks, ETFs, forex, and crypto. It reads live
market data through connected MCP data sources, forms a buy/sell/hold view per symbol
combining technical indicators with qualitative judgment, and simulates trades against
a virtual portfolio it keeps on disk.

> **This never places real orders.** There is no brokerage/exchange execution tool
> wired up — only read-only market data (Twelve Data and/or Crypto.com). All trades are
> simulated for research/practice purposes and are not financial advice.

## Requirements

At least one of these MCP connectors enabled in your session:

- **Twelve Data** — stocks, ETFs, forex, and some crypto pairs; prices, quotes,
  technical indicators, news, earnings, market hours.
- **Crypto.com** — crypto order books, tickers, and candles.

## Usage

```
/trading-agent init 100000 AAPL MSFT BTC/USD
/trading-agent run
/trading-agent run TSLA ETH/USD
/trading-agent status
```

- `init [cash] [symbols...]` — create a fresh paper portfolio with the given starting
  cash (default $100,000) and watchlist.
- `run [symbols...]` — analyze the watchlist (plus any symbols passed in), simulate any
  resulting trades, check existing positions against stop-loss levels, and report.
- `status` — report current holdings and P&L without trading.

## How it works

- **`skills/trading-agent`** drives the workflow: loading/updating the portfolio file,
  applying risk limits, and producing the report. See its `references/` for the exact
  portfolio JSON schema and the default risk rules (position sizing, stop-loss,
  diversification).
- **`agents/market-analyst`** is a read-only subagent dispatched once per symbol (in
  parallel for larger watchlists) to gather price/indicator/news data and return a
  structured signal, which the skill then combines into a final trade decision.
- Portfolio state persists at `.claude/trading-agent/portfolio.json` in your project.

## Contents

| Type | Name | Purpose |
|------|------|---------|
| Command | `/trading-agent` | Entry point: `init`, `run`, `status` |
| Skill | `trading-agent` | Portfolio management, risk rules, report format |
| Agent | `market-analyst` | Per-symbol data gathering and signal generation |
