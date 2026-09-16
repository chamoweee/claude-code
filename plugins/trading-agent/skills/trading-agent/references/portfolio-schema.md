# Portfolio file schema

Path: `.claude/trading-agent/portfolio.json` (relative to the project working directory).

```json
{
  "cash": 100000,
  "starting_cash": 100000,
  "watchlist": ["AAPL", "BTC/USD"],
  "positions": {
    "AAPL": {
      "qty": 10,
      "avg_cost": 231.5,
      "opened_at": "2026-09-10T14:32:00Z",
      "stop_loss_pct": 8,
      "take_profit_pct": null
    }
  },
  "history": [
    {
      "timestamp": "2026-09-10T14:32:00Z",
      "symbol": "AAPL",
      "side": "BUY",
      "qty": 10,
      "price": 231.5,
      "rationale": "RSI oversold bounce + bullish MA crossover, no earnings for 3 weeks"
    }
  ],
  "created_at": "2026-09-10T14:00:00Z",
  "updated_at": "2026-09-10T14:32:00Z"
}
```

Notes:

- `positions` is keyed by symbol; a fully closed position is removed from the map, not
  left at qty 0.
- `avg_cost` is a weighted average when a position is added to across multiple buys.
- `history` is append-only — never rewrite or delete past entries.
- Prices and cash are plain numbers in USD. If the user trades a non-USD pair, still
  record USD-equivalent values (Twelve Data / Crypto.com quotes are already USD-quoted
  for the symbols this skill expects).
- `stop_loss_pct` / `take_profit_pct` are optional per-position overrides; when absent,
  use the portfolio-wide defaults in `risk-rules.md`.
