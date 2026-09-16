Write the top of this week's briefing, and pick three actions.

# What the week's research found

## Macro (already fetched, with week-on-week change)

{{macro_block}}

## Theme status after this week's update

{{themes_block}}

## New opportunities found, with their computed scores

{{opportunities_block}}

## Watchlist

{{watchlist_block}}

# What to produce

**A three-line summary of what changed this week.** Three lines, each one
sentence. Lead with the thing that most changes what the reader should think or
do. If little changed, say that in the first line rather than dressing up a
quiet week — "Nothing material moved; the only change was X" is a perfectly good
opening and builds more trust than manufactured significance.

**Three actions**, each doable in under three hours in an evening or on a
weekend. Good actions are specific and verifiable: "Check whether Mercor accepts
Australian tax residents by reading their contributor terms" beats "look into AI
training work". Each must connect to something in the research above.

An action may be "do nothing about X, and here is what to watch for instead" if
that is genuinely the right call this week.

Do not invent a third action to fill the list. Two good ones beat three padded
ones — return only what you would defend.

# Output shape

```
{
  "summary": ["line one", "line two", "line three"],
  "actions": [
    {
      "rank": 1,
      "title": "Specific, verifiable thing to do",
      "why": "What it answers or unlocks, and what it rules in or out",
      "est_minutes": 90,
      "opportunity_slug": "<slug from above if it relates to one, else empty>"
    }
  ]
}
```

`est_minutes` must be 180 or less. Anything longer is discarded.
