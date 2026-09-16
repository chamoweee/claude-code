# Default risk rules

These are defaults; the user can override any of them explicitly for a session (say so
in the report if they did).

- **Max position size**: no single position may exceed 15% of total equity (cash +
  market value of all positions) at the time it's opened.
- **Max concurrent positions**: 8. Don't open a new one beyond that — report it as a
  pass instead ("signal was BUY but position limit reached").
- **Cash reserve**: never let a buy drop cash below 5% of total equity.
- **Stop-loss**: default -8% from average cost, checked every run against the latest
  price for every open position, before evaluating new signals.
- **Take-profit**: none by default (let winners run) unless the user asks for one or
  the analysis flags a specific reason to trim (e.g. position now >20% of equity due to
  appreciation — trim back toward the 15% cap rather than selling outright).
- **Sizing a new BUY**: use conviction from the signal (strong technical + supportive
  qualitative read → closer to the 15% cap; weak/mixed signal → a smaller starter
  position, e.g. 3-5% of equity) rather than always sizing to the max.
- **Diversification**: avoid putting more than ~40% of equity into a single asset class
  (e.g. all-crypto) unless the user's watchlist itself is single-asset-class, in which
  case this doesn't apply.

## Technical signal inputs

When forming the technical component of a signal, prefer using the Twelve Data
`get_technical_indicator` tool directly (RSI, MACD, SMA/EMA crossovers, Bollinger Bands)
rather than hand-computing from raw candles. Reasonable defaults:

- RSI(14) < 30 → oversold (bullish bias); > 70 → overbought (bearish bias)
- Price crossing above/below its 50-period SMA → trend-following bullish/bearish signal
- MACD line crossing its signal line → momentum confirmation

Treat these as inputs to a judgment call, not a mechanical trigger — cross-check against
recent news (`get_company_news`) and overall market state (`get_market_state`) before
finalizing.
