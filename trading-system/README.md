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
this project is structured to avoid.

### Round 3: a structurally different strategy — cross-sectional momentum

Single-symbol time-series rules (MA/RSI/breakout on one stock at a time)
were never a fair test against that stock's own buy-and-hold, especially
for a concentrated multi-decade compounder like CSL. `scripts/
run_cross_sectional_momentum.py` + `tradesys/backtest/portfolio_engine.py`
try something genuinely different: each month, rank all 12 universe stocks
by trailing 6-month return, hold the top 3, go to cash for any slot where
nothing has positive momentum. This is the actual mechanism behind
published cross-sectional/dual-momentum research, not a retuned version of
the earlier rules — and it's compared against two FAIR benchmarks (VAS
buy-and-hold, and an equal-weight buy-and-hold basket of the same 12
stocks), not against any single stock's own return.

In-sample, monthly rebalancing: **-28.5%**, badly losing to both VAS
(+156.5%) and the equal-weight basket (+326.5%), with 326 trades. But a
zero-fee re-run of the exact same signal returned **+371.8%** — beating
both benchmarks. So unlike the earlier single-symbol rules, this signal
has genuine edge; fees are what's destroying it, not a flawed idea.

Reducing rebalance frequency to fight that fee drag (a specific, motivated
hypothesis, not blind tuning): monthly -28.5% -> quarterly **-47.3%**
(worse) -> semi-annual **+135.8%** (much better, though still short of both
benchmarks). The quarterly result being *worse* than monthly, not a smooth
improvement, is a genuine warning sign — with only ~20 rebalance decisions
across the whole backtest, a single historical path is a small, noisy
sample, and this non-monotonic pattern is exactly what fragile,
path-dependent overfitting looks like from the outside. The semi-annual
number is promising, not proven.

### Round 4: sensitivity sweep + walk-forward (`scripts/validate_momentum.py`)

Built `validation/sensitivity.py` (grid-sweeps lookback x rebalance, checks
whether the surface is broadly stable or spikes at one lucky cell) and
`validation/walk_forward.py` (splits in-sample into sequential windows,
runs one fixed config on each independently). Still in-sample only.

**Sensitivity sweep** (lookback in {63,126,189} x rebalance in
{21,63,126,189}, 12 combos): every 21-day (monthly) rebalance is a heavy
loss regardless of lookback (-28% to -100%) — confirms the fee-drag finding
again. But past that, there's a clear, broadly monotonic pattern: longer
rebalance periods do better, consistently, across all three lookback
values, not just at one cell. 7/12 combos profitable, median +60.8% across
the whole grid. That's a materially different signature than a single
spike surrounded by noise — this looks like a real relationship (trade
less, keep more of the edge), not a fluke.

**Walk-forward** on the specific (lookback=126, rebalance=126) config —
i.e. the one behind the earlier +135.8% headline number — split into 4
independent ~4-year windows: **+3.3%, +64.8%, +20.8%, +1.7%**. Every single
window is positive. Modest in three of the four, strong in one, but never
negative — a strategy that only worked in one lucky stretch would show at
least one deeply negative window here, and it doesn't.

**What this does and doesn't establish**: the (126,126) config now has two
independent pieces of evidence behind it (stable neighbourhood, positive
in every walk-forward window) that the earlier single-number rounds
didn't. The flashier +402-420% results at 189-day rebalance in the sweep
were NOT walk-forward tested and should not be treated as "the best config"
without the same scrutiny — chasing the biggest number in a sensitivity
grid is exactly the mistake this step exists to catch. (126,126) is the
candidate that earned the next step, not the highest number in the table.

**Next**: run (126,126) exactly once against the untouched holdout 20%,
and report that number as final regardless of outcome — see below.

### Round 5: the one-shot holdout check (`scripts/check_holdout.py`)

Holdout window: 2022-10-05 to 2026-09-16 (the last ~4 years, never touched
until this run).

| Approach | Holdout return |
|---|---|
| Cross-sectional momentum (126,126,top3) | **+27.4%** |
| Equal-weight buy-and-hold basket | +44.7% |
| VAS buy-and-hold | +44.6% |

**The candidate loses to both fair benchmarks on holdout**, despite
passing both the sensitivity-neighbourhood check and the walk-forward
consistency check in-sample. Per the rule stated when this script was
written, this result is final — it is not being re-run with a different
config, and no other configuration is being tested against this same
holdout set now (doing so would just turn the holdout into another
in-sample set optimized by hand).

**This is the real value of a holdout set**: everything in round 4 looked
genuinely more robust than rounds 1-3 (broad sensitivity, positive in
every walk-forward window) and still didn't survive contact with data the
strategy had never influenced. That's not a failure of this project — it's
the methodology doing exactly what it's for. As of this run, **no
strategy across 5 rounds of testing has beaten a passive, diversified
benchmark on genuinely out-of-sample ASX data**, after realistic costs, on
a $2,000 account.

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
