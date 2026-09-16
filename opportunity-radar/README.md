# Opportunity Radar

A research agent that scans for money-making trends, investment flows and income
opportunities each week, watches for market alerts each weekday, and emails a
report. See [CLAUDE.md](CLAUDE.md) for the rules and architecture.

**Stage 1 of 5 is built.** Everything below runs today, offline, with no API key
and no cost.

---

## Quick start

```bash
cd opportunity-radar
python3 -m pytest                     # 70 tests, no network
python3 -m radar.cli seed             # write the 16 Sep 2026 baseline
python3 -m radar.cli status           # what it knows, when it runs, what it costs
```

Requires Python 3.11 or newer (for `tomllib` and `zoneinfo`). Stage 1 has no
third-party runtime dependency; `pytest` is the only dev dependency.

### Commands

| Command | Does |
|---|---|
| `radar.cli status` | History counts, next run times, spend, config gaps |
| `radar.cli seed [--force]` | Write the baseline snapshot (idempotent) |
| `radar.cli gate weekly\|daily [--force]` | Would a run fire right now? |
| `radar.cli baseline-gaps` | Baseline claims still lacking a real source |
| `radar.cli reset --yes` | Delete all history and re-seed from empty |

Any command takes `--now <UTC ISO-8601>` to pretend it is another moment, which
is how the daylight-saving behaviour is checked by hand:

```console
$ python3 -m radar.cli --now 2026-09-27T21:00Z gate weekly
RUN: Mon 28 Sep 07:00 AEST — inside the weekly window
$ python3 -m radar.cli --now 2026-10-04T21:00Z gate weekly
SKIP: 08:00 in Sydney; weekly runs in the 07:00 hour (the other UTC cron firing will pick it up)
```

---

## Setup

### 1. Private configuration (local)

Two things are deliberately kept out of this public repo.

```bash
cp config/profile.example.md config/profile.local.md   # then fill it in
export RADAR_RECIPIENT="you@example.com"
```

`config/profile.local.md` is git-ignored. `radar.cli status` says which profile
is in use and warns if it has fallen back to the redacted example — fit scores
from the example are meaningless.

### 2. Anthropic API key (needed from Stage 3)

Create a key at <https://console.anthropic.com/settings/keys>, then:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Budget note: at `claude-sonnet-5` pricing a weekly deep scan with 15–25 web
searches costs roughly $1–3 AUD, and a daily check costs cents. The $30 AUD
monthly cap is enforced in code before every call, so an unexpected loop cannot
run up a bill.

### 3. Gmail API (needed from Stage 4)

One-time setup, about 20 minutes. The helper script arrives in Stage 4; these are
the console steps to do beforehand.

1. Create a project at <https://console.cloud.google.com/>.
2. **APIs & Services → Library →** enable **Gmail API**.
3. **OAuth consent screen →** External, add yourself as a test user. Scope:
   `https://www.googleapis.com/auth/gmail.send` — send only. The agent never
   reads mail.
4. **Credentials → Create credentials → OAuth client ID → Desktop app.** Download
   the JSON; note the client ID and client secret.
5. Run the Stage 4 helper once locally to mint a refresh token:
   `python3 -m radar.mail.authorize`.

### 4. GitHub Secrets (needed from Stage 5)

**Settings → Secrets and variables → Actions → New repository secret.** Never put
any of these in a file.

| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` |
| `RADAR_RECIPIENT` | Where reports are sent |
| `RADAR_PROFILE` | The full contents of `config/profile.local.md` |
| `GMAIL_CLIENT_ID` | From the OAuth client JSON |
| `GMAIL_CLIENT_SECRET` | From the OAuth client JSON |
| `GMAIL_REFRESH_TOKEN` | From the step-5 helper |
| `GMAIL_SENDER` | The Gmail address that sends |

---

## Layout

```
opportunity-radar/
├── CLAUDE.md               goals, hard rules, source rules, architecture
├── config/
│   ├── settings.toml       thresholds, budget cap, pricing, schedule
│   ├── profile.example.md  redacted template (the real one is git-ignored)
│   ├── themes.toml         the seven baseline themes
│   └── watchlist.toml      research watchlist — tickers only, no positions
├── radar/
│   ├── cli.py              the commands above
│   ├── config.py           typed config loading, public vs private split
│   ├── db.py schema.sql    history database
│   ├── gate.py             the daylight-saving gate
│   ├── budget.py           pre-flight spend ceiling
│   ├── runlog.py           run and event logging
│   └── seed_baseline.py    snapshot #1
├── data/radar.db           committed history
└── tests/                  70 tests, no network
```

---

## Known gaps carried into Stage 2

`radar.cli status` surfaces both of these every run; neither is silently ignored.

**Three watchlist tickers are unresolved** and are marked `confirmed = false` in
`config/watchlist.toml`, which stops the price fetcher from quoting a guess:

- `HVLU` — no listing identified.
- `CCL` — Carnival Corp on the NYSE, or the Coca-Cola Amatil ticker that left
  the ASX in 2021?
- `EG` — no unambiguous listing identified.

**Thirteen baseline claims rest on the brief alone.** They are seeded at
strength `weak` and the first weekly deep scan must replace each with a primary
source. `python3 -m radar.cli baseline-gaps` lists them.
