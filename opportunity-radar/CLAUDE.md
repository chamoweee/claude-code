# Opportunity Radar

A recurring research agent that tracks money-making trends, investment flows and
income opportunities, scores them for one specific person, and emails a report.

This file is the contract. When working in `opportunity-radar/`, follow it.

---

## Goal

Chamk has a full-time job, about $1,000 a month spare, and evenings and weekends.
The agent's job is to find, verify and rank things that could make money — and to
be honest when the answer is "nothing new this week". A report that surfaces two
real leads beats one that surfaces ten plausible ones.

The agent researches. It never acts.

---

## Hard rules

These are not style preferences. Code that breaks one of these is wrong.

1. **Research and reporting only.** No trading, no buying, no publishing, no
   account creation, no contacting anyone. The only outbound action the agent
   ever takes is sending email to its own operator.
2. **Investment content is framed as research leads, never advice.** Risks
   stated every time. No price targets presented as predictions.
3. **Spend stops at $30 AUD per month.** Enforced in `budget.py` as a
   pre-flight check before every API call, not as a line in the report. When the
   cap is hit, runs halt until the 1st and one notice email goes out. Every
   report shows month-to-date spend.
4. **Every run is logged** — queries issued, sources consulted, cost, errors — in
   `runs` and `run_events`. A crashed run still leaves its trail.
5. **On failure, email a short error notice.** Silence is a bug.
6. **Never invent a number.** See source rules below.

---

## Source rules

- **Prefer primary sources**: government, regulators, company filings, ABS, RBA,
  major banks. Then reputable media. Blog posts and agency marketing are
  labelled `weak` and say so in the report.
- **Every number needs a source URL and a date.** `validate.py` strips any claim
  that lacks both before it can reach the email. This applies to our own
  baseline too: the 16 Sep 2026 figures are seeded at strength `weak` against
  `baseline://brief` and must be replaced with real sources.
- **When evidence conflicts, show both sides.** Do not pick a winner silently;
  `evidence.conflicts_with` links the pair and the report shows both.
- **Separate "the platform makes money" from "individuals can realistically make
  money".** These are different claims needing different evidence, and they get
  different columns: `platform_revenue_evidence` and
  `individual_earnings_evidence`. A theme where only the first is true is a
  finding in itself — say so.
- **Discovery evidence must be from the last 90 days** (`evidence_max_age_days`).
- **An opportunity supported only by weak sources cannot score above 5.0**
  (`weak_source_score_cap`), whatever the story sounds like. The cap is applied
  in Python and the reason is recorded in `scores.capped_reason`.
- **Red flags** are recorded explicitly: course-selling, hype without revenue,
  MLM structures, pump-and-dump patterns.

---

## Architecture

Deterministic work is Python. Claude does research, judgement and prose. The
split is deliberate and load-bearing.

```
GitHub Actions (UTC cron, two firings)
   └─ gate.py — is it really 07:0x in Sydney? ─── no ──▶ exit 0
         │ yes
         ├─ jobs/weekly.py ─┬─ sources/    macro + watchlist quotes (free, no key)
         │                  ├─ research/   Claude + web search: themes, discovery
         │                  ├─ scoring.py  weighted total from the model's sub-scores
         │                  ├─ report/     mobile-friendly HTML
         │                  └─ mail/       Gmail API
         └─ jobs/daily.py ──┬─ sources/    quotes only
                            ├─ alerts/     pure-Python thresholds
                            └─ mail/       only if an alert fired
   every step ─▶ SQLite (data/radar.db, committed) + budget.py ledger
```

### Why it is split this way

- **Numbers are fetched, not generated.** The 8% / 3% alert thresholds run over
  quotes in SQLite with no model in the loop, so an alert cannot be hallucinated
  or missed. Claude supplies news and interpretation, never arithmetic.
- **Quotes are dated by the exchange, not by Sydney.** A NYSE close and an ASX
  close reached in one 7am fetch belong to different calendar days; dating both
  locally would corrupt every day-on-day change on the US half of the watchlist.
- **A proxy series is labelled as one and never raises an alert.** There is no
  free uranium spot feed, so `URA` (a miner ETF) stands in — stored with a
  `PROXY —` note and excluded from the alert rules. The real uranium price is a
  research question, not a tick.
- **Two cron firings, one gate.** Cron is UTC; Sydney is UTC+10 or UTC+11. Both
  workflows fire at 20:00 *and* 21:00 UTC and `gate.py` asks `zoneinfo` what time
  it actually is in Sydney. Exactly one firing passes on any day, across the
  4 Oct 2026 AEDT switch and every switch after. No date table to maintain.
- **Scoring maths is Python.** The model returns six sub-scores with reasons;
  `scoring.py` computes the total. Auditable, and stable week to week.
- **History is committed.** `data/radar.db` goes into git so week-on-week change
  survives forever and is diffable. Artifacts expire; this does not.

### Privacy

This is a public repository. Therefore:

- `config/profile.local.md` and `data/reports/*.html` are git-ignored.
- The personal profile reaches CI through the `RADAR_PROFILE` secret; the
  recipient through `RADAR_RECIPIENT`. Neither has a committed default.
- `config/profile.example.md` is the redacted template that *is* committed.
- **The committed database must stay non-identifying.** Score rationales
  describe the opportunity ("suits a low-capital evening test"), not the person
  or their address. Theme and config files describe a market ("Sydney's western
  suburbs"), never a specific property or household. The private profile is what
  connects the two, at runtime, in memory. When adding a column, ask whether it
  could carry personal detail into git.

---

## Scoring

Six sub-scores, 1–10, each with a one-line reason from the model:

| Sub-score | 10 means |
|---|---|
| `evidence_strength` | multiple primary sources, recent, consistent |
| `personal_fit` | plugs into an existing asset, audience or skill |
| `capital_fit` | needs almost nothing up front |
| `hours_fit` | works in evenings and weekends |
| `speed_to_dollar` | first dollar within days |
| `risk` | little to lose if it fails (10 = low risk) |

`scoring.py` computes the weighted total from these weights — evidence 0.25,
personal fit 0.20, capital 0.15, hours 0.15, risk 0.15, speed 0.10 — and then
applies two caps, each judged against the raw total so both reasons are
reported even when only the lower one sets the number:

- **`weak_source_score_cap` (5.0)** — nothing better than a blog or a marketing
  page supports it.
- **`no_individual_evidence_cap` (6.0)** — the evidence shows the *platform*
  earns but not that *individuals* do. This is the most common failure mode in
  this space and the brief's central concern, so it is arithmetic, not prose.

The report shows the sub-scores, not just the total — the working is the point.
Opportunities scoring below `personal_fit_threshold` are reported in their own
section rather than dropped or buried.

**Opportunities must not be limited to Chamk's current skills.** Score a poor fit
honestly as a poor fit; do not narrow the search to make the scores look good.

---

## Schedule

| Run | Sydney time | Emails |
|---|---|---|
| Weekly deep scan | Monday 07:00 | Always |
| Daily light check | Weekdays 07:00 | **Only if an alert fires** |

Daily alert triggers: a watchlist stock moving more than 8% in a day; gold,
copper, oil or AUD moving more than 3%; an RBA or Fed decision or major CPI
release; a battery rebate rule change; major news on a tracked theme (IPO,
collapse, regulation, a platform opening to Australians).

---

## Email

Built for a phone, because that is where a 7am email is read. The constraints
are email-client realities, not preferences:

- **Inline styles only.** Gmail strips `<style>` blocks, hardest on mobile.
- **Tables for layout.** Flexbox and grid are unreliable across clients.
- **No external resources** — no web fonts, no images, no tracking pixels.
- **A real plain-text alternative**, which is what survives forwarding.
- **Wide tables stack into rows** rather than scrolling sideways.
- **Under 90KB.** Gmail clips at about 102KB, and the spend and sources section
  at the bottom would be the first thing lost. A test enforces this.

Gmail is reached through its REST API with nothing but the standard library —
two HTTP calls, so `google-api-python-client` and its dependency tree are not
worth it. Scope is `gmail.send` only: the agent cannot read mail. Credentials
come from the environment, are never written to disk, never logged, and are
hidden in `GmailCredentials.__repr__`.

**The weekly report is always sent, even in a quiet week.** A missing Monday
email must mean something broke, never that nothing happened. The daily alert
is the opposite: it sends only when a rule fires.

## Claude API notes

- Model: `claude-sonnet-5` ($2 / $10 per MTok). `claude-opus-5` is priced in
  `settings.toml` but not selected.
- Web search tool type for Sonnet 5 is **`web_search_20260209`**, not the older
  `web_search_20250305`.
- Thinking: `{"type": "adaptive"}` is the only on-mode. `budget_tokens` returns
  a 400. Depth is controlled with `output_config.effort` (`high` weekly, `low`
  daily).
- Sonnet 5 does **not** support mid-conversation system messages; keep operator
  instructions in the top-level `system` field.
- Web search errors return HTTP 200 with an error object inside
  `web_search_tool_result.content` — they do not raise. A successful `content`
  is a list; an error `content` is an object. Branch on that before indexing.
- Prompt caching: keep the stable prefix (system prompt, profile, theme list)
  ahead of the volatile part (this week's date and questions).

---

## Stage status

- [x] **Stage 1 — Foundation.** Config, schema, DST gate, budget guard, run log,
      baseline seed, CLI. No network, no API spend.
- [x] **Stage 2 — Data layer.** Yahoo price source, macro metrics with
      week-on-week change, watchlist quotes, and the alert rule engine. All
      three watchlist tickers resolved. 127 tests, offline fixtures, no API
      spend.
- [x] **Stage 3 — Research engine.** Claude client with web search, the three
      weekly passes, discovery, the scoring rubric with both caps, source
      validation, and cost accounting. 231 tests against a fake SDK, so the
      whole engine is covered at zero spend. Not yet run live.
- [x] **Stage 4 — Report and email.** Mobile-first HTML in the seven-section
      format, plain-text alternative, Gmail API sender on the standard library
      alone, the refresh-token helper, and the error-notice path. 277 tests.
      Never yet sent — no credentials in the build session.
- [ ] **Stage 5 — Automation.** Both workflows, history persistence, secrets
      runbook, dry runs.

## Conventions

- Python 3.11+, standard library only where possible. Stage 1 has no runtime
  third-party dependency at all.
- Tests never touch the network. Fixtures go in `tests/fixtures/`.
- `python -m pytest` from `opportunity-radar/` must pass before any commit.
