# Trading System

A disciplined, testable trading research project: **backtest → paper trade →
gated live execution**, in that order, with strict criteria before real
money is ever risked. This is a research tool, not a money printer — see
`GO_LIVE` criteria in `tradesys/config.py`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,yfinance]"
cp .env.example .env   # fill in TWELVE_DATA_API_KEY if/when you have one
```

## Status

| Mode | Status |
|---|---|
| Backtest | Working — `scripts/run_backtest.py` |
| Paper trade | Not yet built |
| Live (IBKR) | Not yet built — requires running IB Gateway/TWS locally |

## Data source

**Twelve Data** was the intended primary source, but on the currently
connected plan, ASX historical time series (`/time_series`) requires the
Pro/Venture tier and `/splits`+`/dividends` require Grow or above — both
confirmed directly against the API, not assumed. Until/unless that's
upgraded, **yfinance is the practical data source** for the ASX universe.
`tradesys/data/loader.py` already falls back to it automatically; you can
still supply a `TwelveDataClient` as `primary_client` once a suitable plan
is in place.

**Known data quality issue**: `IVV.AX` (S&P 500 exposure) has bad early
history in Yahoo Finance — its pre-2011 data doesn't match its actual ASX
listing (which started ~2011) and there's an unexplained ~20x price drop
around August 2011. Don't trust `period="max"` blindly for cross-listed
ETFs; this needs a start-date guard or anomaly check before IVV backtests
are meaningful (tracked as a follow-up, not yet built).

## Running a backtest

```bash
source .venv/bin/activate
python scripts/run_backtest.py
```

Compares buy-and-hold against a 20/50-day MA crossover across the
configured universe (`tradesys/universe.py`), using real fee/spread/
slippage assumptions from `tradesys/config.py`.

**Current honest result**: the naive MA(20,50) crossover loses to
buy-and-hold on every symbol tested, after realistic fees. That is not a
bug to "fix" by tuning parameters until it looks better — a strategy that
only wins after parameter search on the same data it's judged by is
exactly the overfitting this project is structured to avoid (see
`validation/`, not yet built, for walk-forward + out-of-sample holdout).
Right now this is a plain result: on this universe and cost model, MA
crossover is not yet a candidate for real money.

## Running the tests

```bash
source .venv/bin/activate
python -m pytest -q
```

## Project layout

See inline module docstrings. Rough shape:

- `tradesys/config.py` — account size, risk limits, cost model, go-live
  criteria: the one place these numbers live.
- `tradesys/universe.py` — fixed symbol list, chosen up front to avoid
  survivorship bias from "today's index membership" lookups.
- `tradesys/data/` — loading (Twelve Data + yfinance fallback), caching,
  split/dividend back-adjustment.
- `tradesys/strategies/` — pluggable `Strategy` interface; `buy_and_hold`
  (the benchmark every strategy must beat) and `ma_crossover` so far.
- `tradesys/backtest/` — event-driven engine (next-bar execution only, no
  look-ahead), transaction cost model, portfolio ledger.
- `tradesys/risk/` — fee-aware position sizing (1% account risk per trade).
- `tradesys/validation/`, `tradesys/execution/`, `tradesys/reporting/` —
  not yet built.
