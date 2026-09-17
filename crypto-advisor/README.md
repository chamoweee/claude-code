# Crypto Screening & Advisory Agent

A Python agent that screens cryptocurrencies against a configurable set of
filters, runs a live auto-refreshing market report, and produces transparent,
rules-based BUY / ADD / HOLD / TRIM / SELL / WATCH advice for both new coins
and coins you already hold. Built for an Australian investor who wants
steadier, lower-risk exposure within crypto.

**Scope: cryptocurrencies only.** No stocks, ETFs, or other asset classes.

**Advisory only.** This agent never connects to an exchange account with
trading permissions and never places trades -- it only reads public market
data. Every signal and insight is rule-based research output, not financial
advice, and cites the exact numbers that triggered it. Missing data is shown
as N/A (with lower confidence), never guessed.

---

## 1. Setup

```bash
cd crypto-advisor
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # fill in whatever keys you have (all optional)
cp portfolio.example.yaml portfolio.yaml   # then edit with your real holdings
```

Requires Python 3.11+.

## 2. API keys (`.env`)

All keys are optional -- the agent degrades gracefully and logs what it
skipped when a key is missing:

| Variable | Used for | If missing |
|---|---|---|
| `COINGECKO_API_KEY` | Higher CoinGecko rate limit (free "Demo" key) | Falls back to the public API's default rate limit (slower) |
| `ANTHROPIC_API_KEY` | The optional plain-English "what matters today" summary via the Claude API | That section is skipped entirely |
| `CCXT_EXCHANGE` | Which exchange (`kraken` default, or `binance`) ccxt cross-checks 30d volume against | Defaults to `kraken` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` / `SMTP_TO` | Daily digests and instant high-priority alert emails | Email is disabled; the live loop still runs and writes `output/live_report.html` |

No exchange account credentials are ever requested or used -- only public
market-data endpoints (CoinGecko, ccxt public OHLCV, Binance's public
WebSocket ticker stream, DefiLlama).

## 3. Your portfolio (`portfolio.yaml`)

```yaml
cash_aud: 2000.0
holdings:
  - coin_id: bitcoin        # CoinGecko id -- check https://api.coingecko.com/api/v3/coins/list
    units: 0.05
    cost_base_aud: 4200.00  # total AUD paid, including fees
    purchase_date: "2023-11-10"
    exchange: "Kraken"
watchlist:
  - solana
  - chainlink
```

`portfolio.yaml` is gitignored (it's your personal data) -- edit your own
copy from `portfolio.example.yaml`. All figures are AUD.

## 4. Running it

```bash
python main.py screen      # build the investable universe -> output/screen.csv (no advisory)
python main.py advise      # full pipeline incl. actions   -> output/actions.md, live_report.html
python main.py simple      # condensed view: top movers/losers + BUY/ADD potentials -> prints to terminal
python main.py backtest    # walk-forward backtest vs benchmarks -> output/report.md
python main.py live        # runs `advise` on a loop (default every 5 min), with alerts + digests
streamlit run dashboard.py # mobile-friendly live dashboard (reads output/state.json)
```

`simple` is the quickest way to check in: it prints (and writes to
`output/simple_report.md`) just the top movers beyond
`config.yaml`'s `simple_report.mover_threshold_pct` (default +/-20%), the top
losers beyond it, and the coins currently eligible for BUY/ADD -- each with a
real historical 1-week return range (the actual 10th-90th percentile of that
coin's trailing 7-day returns), not a forecast. If nothing currently clears
the BUY/ADD bar, it shows the closest candidates by score instead, clearly
labelled as such. Every other command also writes `simple_report.md` as part
of its normal output, so it's always there to re-read.

`live` and the dashboard are meant to run together: `python main.py live` in
one terminal (or as a background service, see below) keeps
`output/state.json` and `output/live_report.html` fresh, and the Streamlit
dashboard just displays them (it never calls the APIs itself, so it can't
blow your rate limit no matter how often you refresh the page).

## 5. Tuning thresholds (`config.yaml`)

Every filter, classification threshold, risk limit, alert threshold and the
refresh interval lives in `config.yaml`, grouped by section (`universe`,
`classification`, `movers`, `insights`, `signals`, `risk`, `au_tax`,
`alerts`, `backtest`, `data_sources`). Nothing is hardcoded in the modules --
open `config.yaml`, read the inline comments, and adjust. A few worth
knowing about:

- `universe.max_coins_scanned` (default 80) caps how many CoinGecko-ranked
  coins get the full history/volume/exchange checks each run, to stay
  within the free API tier's rate limit. Raise it if you have a paid
  CoinGecko key (set `COINGECKO_API_KEY`).
- `risk.max_position_pct_per_coin`, `risk.max_total_speculative_allocation_pct`,
  `risk.min_core_allocation_pct` control the position-sizing/risk-budget gates
  described below -- the defaults (15% / 20% / 50%) lean toward the "steadier,
  lower-risk" preference this agent was built for.
- `data_sources.defillama_slug_map` maps CoinGecko ids to DefiLlama protocol
  slugs for fees/revenue data. It's a small, maintained, inherently
  incomplete list -- coins not in it show fees/revenue as N/A rather than a
  guess. Add more mappings as needed.

## 6. How it works

**Universe** (`universe.py`): pulls the full CoinGecko coin list + market
data, excludes stablecoins/wrapped-bridged tokens/liquid-staking
derivatives/exchange-pegged tokens (by CoinGecko category, backed by a small
denylist), then requires a minimum market cap, minimum 30-day average
volume, minimum price history, and a listing on at least one major exchange.
Every excluded coin is logged to `data/excluded_coins_log.csv` with its
specific reason and value.

**Classification** (`classify.py`): each coin that passes the universe
filter is tagged `core` (BTC/ETH-tier cap, liquidity and history),
`revenue-generating` (fees/revenue present in >=6 of the last 8 quarters and
low supply inflation), or `speculative` (everything else). Only `core` and
`revenue-generating` coins are ever eligible for a BUY/ADD action -- this is
a hard gate in `risk.py`, not a scoring weight.

**Advisory** (`signals.py` + `risk.py`): a composite, fully transparent
score = weighted fundamentals + valuation + trend + market-regime
components (weights in `config.yaml`). The score maps to a candidate action,
and `risk.py` then applies hard gates that can only ever *downgrade* it:
classification eligibility, per-coin position cap (forces TRIM), total
speculative allocation cap, a trailing stop (forces SELL), and a
fundamentals-broke trigger (classification downgrade, a large flagged token
unlock, or the coin no longer returning CoinGecko market data at all --
possible delisting). **A coin being a top mover is never an input to the
score** -- see `tests/test_signals.py::test_top_mover_status_never_affects_score`.

**Live report** (`movers.py`, `insights.py`, `report.py`, `dashboard.py`,
`alerts.py`, `scheduler.py`): `scheduler.py` runs the full pipeline on a
loop, writing `output/screen.csv`, `output/actions.md`, `output/report.md`,
`output/live_report.html`, `output/charts/*.png` and `output/state.json`
every cycle, appending to `data/signals_history.csv` and
`data/live_history/`, checking instant alerts (cooldown-gated) and the two
daily digests each cycle.

**Australian tax** (`au_tax.py`): every SELL/TRIM shows the unrealised AUD
gain/loss from your recorded cost base, flags holdings within 60 days of the
12-month CGT discount date, always notes that swapping crypto-for-crypto is
a CGT event, and nets the suggested trade against a configurable per-exchange
fee/spread estimate. **General information only, not tax advice** -- confirm
with a registered tax agent before acting.

**Backtest** (`backtest.py`): a walk-forward backtest built from the price
history already fetched into the universe (no extra API calls), from 2017
(covering the 2018 and 2022 bear markets) to today, using only data
available as of each rebalance date. Compares BTC buy-and-hold, a 70/30
BTC/ETH portfolio, an equal-weight basket of the filtered universe, a naive
"buy yesterday's top mover" sanity check, and a simplified version of the
signal rules (trend + classification-eligibility only -- see the module
docstring for why historical fundamentals can't be reconstructed on the free
API). Reports CAGR, max drawdown, volatility, win rate, trade count and
estimated costs.

## 7. Keeping the live report running

`python main.py live` runs in the foreground until you Ctrl+C it. To keep it
running unattended:

- **A small always-on machine or VPS** (recommended): run it inside `tmux`/
  `screen`, or as a `systemd` service, e.g.:
  ```ini
  # /etc/systemd/system/crypto-advisor.service
  [Service]
  WorkingDirectory=/path/to/crypto-advisor
  ExecStart=/path/to/crypto-advisor/.venv/bin/python main.py live
  Restart=on-failure
  ```
- **cron** (Linux/macOS): since `live` is a persistent loop rather than a
  one-shot job, cron is a better fit for the daily digests/single runs --
  e.g. `*/5 * * * * cd /path/to/crypto-advisor && .venv/bin/python main.py advise`
  re-runs the full pipeline (incl. writing `state.json` and checking alerts)
  every 5 minutes without needing a long-running process.
- **Windows Task Scheduler**: create a task that runs
  `python main.py advise` on a 5-minute trigger, "Start in" set to the
  `crypto-advisor` folder.
- Run `streamlit run dashboard.py` (or `streamlit run dashboard.py --server.headless true`
  on a server) separately, wherever you want to view it from.

## 8. Testing

```bash
pytest
```

All tests use fixture data and mock/fake clients -- no network calls. They
cover universe filters, metrics math (volatility/drawdown/beta against
synthetic series with known answers), movers ranking and the liquidity
split, each insight rule, classification boundaries, signal rules (including
the "speculative can't BUY" and "top-mover alone never triggers BUY"
regressions), alert cooldowns, and risk limits (position caps, trailing
stop, fundamentals-broke sell).

## 9. Output files

| File | Contents |
|---|---|
| `output/screen.csv` | Every metric for every universe coin |
| `output/live_report.html` | Static snapshot of the live report (mobile-friendly), regenerated every cycle |
| `output/actions.md` | Today's actions table, reasons per coin, allocation summary, changes since last run |
| `output/report.md` | Backtest comparison, bull/bear per coin, excluded-coin summary, data-quality section |
| `output/charts/` | Movers heatmap, sector performance, drawdown/volatility comparison, BTC-beta scatter, backtest equity curves |
| `output/state.json` | Compact snapshot the Streamlit dashboard reads |
| `data/excluded_coins_log.csv` | Every coin excluded from the universe, with its reason |
| `data/data_quality_log.csv` | Every missing/suspicious field encountered, with source and field |
| `data/signals_history.csv` | Every action ever produced, appended each run |
| `data/live_history/` | Per-refresh mover/insight snapshots |
| `data/decisions_journal.csv` | You fill this in with what you actually did (see `decisions_journal.example.csv`); `report.md`'s "changes since last run" section and future tooling can diff it against `signals_history.csv` |

## 10. Known limitations

- **Free CoinGecko rate limits** cap how large/fast a full-universe scan and
  the multi-year backtest can run without heavy caching. `data/raw/` caches
  every response with a per-endpoint TTL so re-runs don't refetch, and
  `universe.max_coins_scanned` bounds the scan size -- both are tunable, but
  a full top-300+ scan on the free tier will still take a while.
- **Historical circulating supply and token-unlock schedules** are only
  available for some coins on free data sources. Where unavailable, the
  figure is N/A and the confidence on any signal relying on it is capped --
  never estimated.
- **The backtest is not fully survivorship-bias-free.** CoinGecko's free API
  cannot reliably reconstruct which coins were in the investable universe (or
  recover history for delisted/collapsed coins) at each historical date. The
  backtest uses today's classification and coin set applied to available
  historical prices -- a genuine gap, stated in `output/report.md`, not
  worked around.
- **Binance's public WebSocket** (used for near-real-time price streaming in
  `stream.py`) may be geo-blocked on some networks (it returned HTTP 451 in
  this project's own development sandbox). The REST-polling fallback covers
  that automatically and the report shows a stale-data warning when it's
  active, but verify live WS behaviour once running somewhere with
  unrestricted egress.
- **DefiLlama protocol-to-coin mapping** (`config.yaml`
  `data_sources.defillama_slug_map`) is a small, maintained, inherently
  incomplete list. Coins not in it show fees/revenue/price-to-fees as N/A.
- **The Claude-generated summary** (when `ANTHROPIC_API_KEY` is set) is
  instructed to cite only the figures it's given and nothing else, but like
  any model output it should be read as a convenience summary, not a
  substitute for the tables and reasons above it.

## 11. Disclaimer

Signals and insights are rule-based research output based on public market
data, not financial advice. AU tax notes are general information only, not
tax advice. This tool does not connect to any exchange account with trading
permissions and never places trades.
