# Opportunity Radar

A research agent that scans for money-making trends, investment flows and income
opportunities each week, watches for market alerts each weekday, and emails a
report. See [CLAUDE.md](CLAUDE.md) for the rules and architecture.

**All five stages are built.** Everything below runs today with no API key
and no cost. The research engine and the email sender are tested but have not
yet been run against the real API or a real inbox, and **both workflow schedules
ship deactivated** — see *Going live* below.

---

## Quick start

```bash
cd opportunity-radar
python3 -m pytest                     # 302 tests, network blocked by conftest
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
| `radar.cli prices [--store]` | Live macro + watchlist fetch and alert preview (free) |
| `radar.cli research weekly\|daily` | Price the research passes without calling the API |
| `radar.cli research weekly --live` | Run the real deep scan (spends money) |
| `radar.cli preview` | Render a sample weekly email to a file (free, sends nothing) |
| `radar.cli send-test` | Send one test email, to prove Gmail works |
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

Measured worst-case ceilings, from `radar.cli research`:

| Pass | Searches | Worst case |
|---|---|---|
| Weekly deep scan (3 calls) | 30 | **$2.16 AUD** |
| Daily check (1 call) | 6 | **$0.40 AUD** |

A full month — four weekly scans plus about 21 daily checks — has a worst case
near **$17 AUD** against the $30 cap, and real runs come in well under, since
the estimate assumes every search is used and every response hits its token
ceiling. The cap is enforced before each call, so a loop cannot run up a bill.

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
5. Run the helper once locally to mint a refresh token — it opens the consent
   screen, catches the redirect and prints the token:
   `python3 -m radar.mail.authorize`

Then check it end to end:

```bash
export GMAIL_CLIENT_ID=... GMAIL_CLIENT_SECRET=... GMAIL_REFRESH_TOKEN=...
export GMAIL_SENDER="<your gmail address>"
export RADAR_RECIPIENT="<where reports should go>"
python3 -m radar.cli send-test
```

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
│   ├── seed_baseline.py    snapshot #1
│   ├── sources/            Yahoo price source, macro metrics, watchlist quotes
│   ├── alerts/rules.py     the 8% / 3% threshold engine
│   ├── research/           Claude client, prompts, validation, scoring, engine
│   ├── report/             mobile-first HTML + plain text rendering
│   ├── mail/               Gmail API sender and the refresh-token helper
│   └── jobs/               weekly.py, daily.py, and the shared failure path
├── data/radar.db           committed history
└── tests/  fixtures/       302 tests; conftest blocks all sockets
```

---

## Data sources

Prices come from the Yahoo Finance chart API: no key, no rate limit to manage,
and it covers ASX and US listings plus commodity futures and FX in one shape.
Quotes are dated in the exchange's own timezone. Yahoo is an aggregator rather
than the exchange, so readings are recorded at `reputable_media` strength.

`uranium_ura_proxy` is the one deliberate compromise. No free U3O8 spot feed
exists, so the Global X Uranium ETF stands in — stored with a `PROXY —` note and
excluded from the alert rules, because a miner ETF moving 10% is not a uranium
price move. The real uranium price is handled by research in Stage 3.

Interest-rate decisions and CPI are not market ticks and are not fetched here;
they come from primary sources via research.

## Known gaps carried into Stage 3

**Thirteen baseline claims rest on the brief alone.** They are seeded at
strength `weak` and the first weekly deep scan must replace each with a primary
source. `python3 -m radar.cli baseline-gaps` lists them.

**`EG` was resolved by lookup, not by the brief.** It is set to Everest Group,
Ltd. (NYSE) — the only equity trading under that ticker. Correct
`config/watchlist.toml` if a different security was meant.

**`CCL` is recorded as delisted.** Coca-Cola Amatil was acquired by Coca-Cola
European Partners in 2021. It is kept in the watchlist marked `active = false`
so the gap in history explains itself, and is never quoted. The successor entity
is Coca-Cola Europacific Partners (NASDAQ/LSE: CCEP) if that business is still
of interest.


---

## Going live

Both workflows ship with their `schedule:` blocks commented out, so nothing
fires until you turn it on. Work through this in order.

**1. Add the secrets** (the table above). `radar.cli status` tells you which are
still missing.

**2. Prove email works.**

```bash
python3 -m radar.cli send-test
```

**3. Run each workflow by hand.** Actions → *Radar daily* → Run workflow, with
**dry run** ticked. Then *Radar weekly* the same way. A dry run does everything
except send, so you can read the log and the uploaded report artifact first.

**4. Run the weekly for real** — untick dry run. This is the first time money is
spent. Expect roughly $1–3 AUD; the log prints the exact figure.

**5. Uncomment the `schedule:` blocks** in
`.github/workflows/radar-weekly.yml` and `radar-daily.yml`, and push.

### What the schedule means

| Workflow | Cron (UTC) | Sydney |
|---|---|---|
| Weekly | `0 20 * * 0` and `0 21 * * 0` | Monday 07:00 |
| Daily | `0 20 * * 0-4` and `0 21 * * 0-4` | Mon–Fri 07:00 |

Two firings each because cron only speaks UTC and Sydney moves between UTC+10
and UTC+11. Both start the job; `radar.gate` asks `zoneinfo` what time it
actually is in Sydney and the wrong one exits 0 in about a second, having spent
nothing. No maintenance across any future daylight-saving change.

### Where history lives

`.github/scripts/radar-history.sh` moves `data/radar.db` between the runner and
a dedicated **`radar-data`** branch, so a weekday of bot commits never lands in
your code history. It uses git plumbing rather than checking the branch out, so
it never switches branch and cannot leave a run on the wrong ref. That branch
holds exactly one file, `radar.db`, with one commit per run that changed it.

To inspect it locally:

```bash
git fetch origin radar-data
git cat-file blob origin/radar-data:radar.db > /tmp/radar.db
sqlite3 /tmp/radar.db "SELECT sydney_date, kind, status, notes FROM runs ORDER BY id DESC LIMIT 10;"
```

### Reading the Actions result

| Outcome | Means |
|---|---|
| Green, no email (daily) | Nothing breached a threshold. The normal weekday. |
| Green, no email (weekly) | Should not happen — the weekly always sends. |
| Green, "skip:" in the log | The wrong UTC firing. The other one did the work. |
| Green, budget notice | The $30 cap was reached. Runs resume on the 1st. |
| Red | Something broke, and a notice email was attempted. |
