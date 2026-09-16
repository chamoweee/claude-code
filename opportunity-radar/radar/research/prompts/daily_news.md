This is the weekday morning check, not the weekly deep scan. Be fast and be
quiet unless something genuinely happened.

Today is {{today}}. Look only for events in the last 48 hours.

# Trigger on any of these, and nothing else

1. **An RBA or US Federal Reserve rate decision**, or a major CPI release for
   Australia or the US. The decision or the number, not commentary about it.
2. **A change to Australian home battery rebate rules** — rate, eligibility,
   the step-down schedule, or a state scheme.
3. **Major news on a tracked theme**: an IPO or a filing for one, a collapse or
   administration, a regulatory change, or a platform opening to or closing off
   Australians.

# The tracked themes

{{themes_block}}

# What does not count

Price moves are handled separately by a threshold check and must not be
reported here. Opinion pieces, analyst forecasts, "could", "may", "is expected
to", and previews of events that have not happened are not triggers. A meeting
that is scheduled is not news; the decision it produces is.

# The bar

This email wakes someone up at 7am on a work day. If nothing on the list above
actually happened, return `{"alerts": []}`. That is the expected answer on most
days and it is the correct one. Do not lower the bar to have something to say.

# Output shape

```
{
  "alerts": [
    {
      "rule": "rate_decision|cpi_release|battery_rebate|theme_news",
      "subject": "<tracked theme slug, or 'RBA', 'Fed', 'CPI'>",
      "headline": "What happened, in one line",
      "detail": "What it means for the tracked theme, in 1-3 sentences",
      "source_url": "https://...",
      "source_date": "2026-09-16",
      "severity": "info|notable|urgent"
    }
  ]
}
```
