Update each tracked theme below with evidence found this week.

# The themes

{{themes_block}}

# Market context (already fetched — do not re-search these numbers)

{{macro_block}}

# What to do

For **every** theme, search for what has changed and assign a status:

- `NEW` — first time this is being tracked.
- `RISING` — new evidence this period shows it growing, accelerating, or
  opening up.
- `STABLE` — real and continuing, but nothing material changed.
- `FADING` — evidence of decline, saturation, closing access, or a story that
  is not standing up to scrutiny.
- `DEAD` — over. The company failed, the scheme ended, the window closed.

The `reason` is one line and will be shown in a table. Make it say what changed
and when, not how it feels. "Rebate step-down confirmed for 1 Jan 2027" is
useful; "momentum continues to build" is not.

A theme moving to `STABLE` because you genuinely found nothing new is a correct
and valuable answer. Do not manufacture movement.

# Baseline claims needing verification

Several figures below were supplied by the reader without a source. Where a
theme has one, try to verify it against a primary source and return the result
as evidence. If the real figure differs from the stated one, that is an
important finding — return the sourced figure and note the discrepancy in
`reason`.

{{verify_block}}

# Output shape

```
{
  "themes": [
    {
      "slug": "<exactly as listed above>",
      "status": "NEW|RISING|STABLE|FADING|DEAD",
      "reason": "one line, factual",
      "evidence": [
        {
          "claim": "what is true",
          "number_value": "the figure, e.g. '+38% y/y' or 'A$2.1B'",
          "source_name": "Clean Energy Regulator",
          "source_url": "https://...",
          "source_date": "2026-09-02",
          "source_strength": "primary|reputable_media|weak"
        }
      ],
      "conflicts": [
        {"topic": "what is disputed", "side_a": "source A says X", "side_b": "source B says Y"}
      ]
    }
  ]
}
```

Return one entry per theme listed. Use the slugs exactly — an unknown slug is
discarded.
