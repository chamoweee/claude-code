Find up to {{max_new_trends}} money-making trends that are **not** already
tracked, from any industry.

# Already tracked — do not return these again

{{existing_block}}

# The bar

Each candidate must have **verifiable revenue or growth data published in the
last {{max_age_days}} days**. Not a trend piece, not a prediction, not a
"fastest growing" listicle — a number, from a source, with a date. Anything
older than that window will be deleted before the reader sees it.

Search widely. Do not confine yourself to technology, to online work, or to
things this particular reader could do. Regulation changes, demographic shifts,
supply chains, trades, local services, agriculture, logistics, healthcare,
energy and property all count. Some of the best findings will be things the
reader has never considered.

**Returning fewer than {{max_new_trends}} is correct if fewer than
{{max_new_trends}} clear the bar.** Returning zero with an honest explanation is
better than padding. Do not include something you would not defend.

# For each one

Answer these separately and concretely:

- **Who actually earns the money?** The platform, the landlord, the licence
  holder, the middleman, the worker? Be specific about which party captures the
  margin.
- **`platform_revenue_evidence`** — what the business or sector is earning.
- **`individual_earnings_evidence`** — evidence that an *individual* is
  realistically earning, with figures and a source. **Leave this empty if you
  could not find it.** Do not fill it with the platform's numbers, aspirational
  ranges, or testimonials from people selling a course. An empty field here is a
  finding, and the report will say so.
- **Startup cost** in AUD, as a realistic range including the things people
  forget: equipment, licensing, insurance, compliance.
- **Time to first dollar**, in days, honestly. Include waiting lists, approval
  times and onboarding.
- **Skills and credentials** genuinely required, including anything licensed.
- **Saturation** — how crowded is it already, and who is the incumbent?
- **Red flags** — name them. If the loudest voices are selling a course about
  it, say so. If you found no red flags, say that plainly.
- **Australian eligibility** — can someone in Australia actually access this?
  Many platforms are US-only, or restricted by tax residency, visa status or
  banking. Check, and say if you could not determine it.

# Scoring

Score each 1-10 with a one-line reason for each:

- `evidence_strength` — 10 is several recent primary sources agreeing.
- `personal_fit` — for the reader described in your instructions. Score this
  honestly. A 2 is a perfectly good answer for a real trend that does not suit
  them.
- `capital_fit` — 10 means it needs almost nothing up front.
- `hours_fit` — 10 means it works in evenings and weekends.
- `speed_to_dollar` — 10 means a first dollar within days.
- `risk` — 10 means little to lose if it fails. **Low risk scores high.**

# Output shape

```
{
  "opportunities": [
    {
      "slug": "short-kebab-case-id",
      "title": "Plain description",
      "summary": "2-4 sentences on what this actually is",
      "theme_slug": "<a tracked slug if it belongs to one, else empty>",
      "who_earns": "...",
      "platform_revenue_evidence": "...",
      "individual_earnings_evidence": "... or empty",
      "startup_cost_aud_min": 0,
      "startup_cost_aud_max": 2000,
      "time_to_first_dollar_days": 30,
      "skills_required": "...",
      "saturation": "...",
      "red_flags": "...",
      "au_eligibility": "...",
      "evidence": [
        {"claim": "...", "number_value": "...", "source_name": "...",
         "source_url": "https://...", "source_date": "2026-08-20",
         "source_strength": "primary|reputable_media|weak"}
      ],
      "scores": {
        "evidence_strength": 7, "personal_fit": 4, "capital_fit": 9,
        "hours_fit": 6, "speed_to_dollar": 5, "risk": 6,
        "reasons": {
          "evidence_strength": "two government releases plus one filing",
          "personal_fit": "requires a licence they do not hold"
        }
      }
    }
  ],
  "notes": "Anything you looked at and rejected, and why."
}
```
