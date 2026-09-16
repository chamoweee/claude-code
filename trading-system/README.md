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

**Data quality guard (fixed)**: `IVV.AX` had bad early history in Yahoo
Finance. `tradesys/data/quality.py` now detects any unexplained >3x (or
<1/3x) single-day price jump and truncates everything before the *last*
such jump, keeping only the most recent clean stretch. For IVV this cut off
data before 2015-12-29 (there were actually two bad discontinuities, not
just the one near its 2011 ASX listing — the guard conservatively keeps
only what's after the last one). That leaves ~11 years of usable IVV
history instead of the bogus ~18. This is a blunt, single-symbol guard, not
a general data-vendor reconciliation — worth remembering if a similar
issue shows up in the wider universe later.

## Running a backtest

```bash
source .venv/bin/activate
python scripts/run_backtest.py
```

Compares buy-and-hold against three candidate strategies (MA(20/50)
crossover, RSI/Bollinger mean reversion, Donchian momentum breakout) across
the configured universe (`tradesys/universe.py`), using real fee/spread/
slippage assumptions from `tradesys/config.py`.

**Current honest result**: all three strategies lose to buy-and-hold on
every symbol tested, after realistic fees — often losing 40-90% while
buy-and-hold gains hundreds of percent. That is not a bug to "fix" by
tuning parameters until it looks better (see `validation/`, not yet built,
for walk-forward + out-of-sample holdout — the real defence against that).

Two genuinely separate causes, isolated by re-running CBA with fees zeroed
out (not a permanent code change, just a diagnostic):

1. **Fee drag is severe at this account size.** All three strategies trade
   100-230 times over ~20 years at average notional of only ~$100-200 a
   trade. The $9.90 minimum brokerage alone is 5-10% of a typical trade's
   notional — total fees paid over the backtest exceed half the starting
   $2,000 capital. Zero-fee, the strategies are roughly flat-to-slightly-
   positive (MA +13%, mean reversion +18%, breakout +6.5% on CBA); with
   real fees applied, all three go deeply negative. **A $2,000 account
   cannot absorb this many round trips regardless of strategy quality** —
   this is a capacity/design constraint, not something a better entry rule
   fixes.
2. **Even fee-free, none of them get close to buy-and-hold** (+13-18% vs
   +775% on CBA over the same window). Spending time out of the market
   during a multi-decade one-directional bull run in a strong compounder
   like CBA is extremely costly — a well-documented property of timing
   strategies, not obviously a flaw in these three specific rules.

Neither finding says "this approach can never work" — they say: don't trust
any of these three at the current trade frequency on a $2,000 account, and
don't conclude anything about raw signal quality without separating it from
fee drag first, the way we just did.

### Round 2: fewer, higher-conviction trades (`scripts/search_strategies.py`)

Acting on that diagnosis, four lower-frequency variants were tried —
**in-sample only** (`tradesys/validation/holdout.py` splits off the last
20% of each symbol's history; it was not touched for this search): a
50/200 "golden cross" MA, a wider 55/20 Donchian channel, a 20/10 breakout
gated to only fire >=1.5 ATR clear of the range, and mean reversion
requiring RSI *and* price both oversold instead of either.

Result: trade counts dropped a lot (24-81 vs. 100-230 before) and losses
shrank a lot (+1% to -38% vs. -41% to -93% before) — the fee-drag diagnosis
holds up. **But 0 of the 4 variants beat buy-and-hold on any of the 14
symbols.** Buy-and-hold averaged +342% in-sample; even the best variant
(MA 50/200) only managed +1.3% average.

This is reported as a real result, not a prompt to keep grid-searching
parameters until something crosses zero — that's exactly the overfitting
this project is structured to avoid. The more useful next questions are
probably: (a) these are total-return comparisons only — risk-adjusted
metrics (Sharpe, max drawdown) aren't built yet and could tell a different
story even without beating raw buy-and-hold return; (b) mean
reversion/breakout strategies are generally expected to show an edge in
choppier, range-bound markets, not a one-directional multi-decade blue-chip
bull run — the current universe/period may simply be a bad test bed for
them; (c) for a $2,000 account, buy-and-hold plus disciplined fortnightly
contributions may honestly be the better answer to "what strategy" than
any active timing rule tested so far.

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
  split/dividend back-adjustment, and a basic bad-data-jump guard.
- `tradesys/strategies/` — pluggable `Strategy` interface; `buy_and_hold`
  (the benchmark every strategy must beat), `ma_crossover`, `mean_reversion`
  (RSI + Bollinger Bands), `momentum_breakout` (Donchian channel).
- `tradesys/backtest/` — event-driven engine (next-bar execution only, no
  look-ahead), transaction cost model, portfolio ledger.
- `tradesys/risk/` — fee-aware position sizing (1% account risk per trade).
- `tradesys/validation/`, `tradesys/execution/`, `tradesys/reporting/` —
  not yet built.
