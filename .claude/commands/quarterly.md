---
description: Run the quarterly CMC Invest review — full fee/fund/CGT verification, portfolio summary, and up to 3 proposed changes for Chamk to approve.
---

Run the quarterly review. Follow `CLAUDE.md` for all hard rules — this command never edits `config/portfolio.json` without Chamk's explicit approval, and never proposes a sell to fix drift.

1. **Full verification.** Invoke the `market-data` agent to do its quarterly job: re-verify CMC Invest's fee schedule and brokerage rules, check A200/BGBL/VVLU and alternates for fee/size/mandate changes, search for any cheaper like-for-like ETF (lower fee, > $500M size) in each sleeve, and check the status of the 2026-27 CGT discount change (still proposed / introduced / law). It reports findings with sources; it does not edit config.
2. **Portfolio summary.** Invoke the `ledger-keeper` agent to produce the quarterly summary: total contributed, current value, unrealised gain/loss, distributions received, fees paid (management + brokerage), weights vs target, and parcels approaching/past the 12-month CGT mark. Remind Chamk to keep his annual tax statements.
3. **Audit proposed changes.** If `market-data` surfaced any potential change (cheaper alternate, fee change, fund issue, CGT law status change), invoke the `compliance-auditor` agent to sanity-check each proposal: confirm any switch wouldn't breach the overlap rules, and that switching would only apply to new money (never sell to switch) unless Chamk explicitly asks about a sell.
4. **Present decisions.** Show Chamk, mobile-friendly:
   - The portfolio summary table (value, gain, fees, weights vs target).
   - **At most 3 proposed decisions** (e.g. "switch new BGBL contributions to a cheaper alternate", "fees_verified date update", "CGT law status changed — see note"), each as a one-line ask with the supporting fact and source.
   - A note on any parcels newly past 12 months (relevant only if Chamk later asks about selling).
5. **Apply only on approval.** If Chamk approves any of the proposed decisions, update `config/portfolio.json` accordingly (e.g. new `fees_verified` date, a sleeve's ticker/fee if he approves a switch for new money only). Do not change anything he didn't approve.
