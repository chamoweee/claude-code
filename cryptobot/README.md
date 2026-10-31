# cryptobot

A small, dependency-free crypto trading bot for Node 18+. It reads public market data from the
[Crypto.com Exchange](https://exchange-docs.crypto.com/) API (no API key) and **paper trades only**:
it simulates fills with fees and slippage, and never places real orders.

## Strategy

EMA crossover with an RSI filter, evaluated on each closed candle:

- **Buy** when the fast EMA (12) crosses above the slow EMA (26) and RSI (14) is ≤ 70.
- **Sell** when the fast EMA crosses back below, or on a 3% stop loss / 6% take profit.

Every parameter can be changed with a flag.

## Usage

```bash
cd cryptobot
node src/cli.js price --symbol ETH_USD
node src/cli.js backtest --symbol BTC_USD --timeframe 1h --candles 2000 --trades
node src/cli.js run --symbol BTC_USD --timeframe 15m          # live paper trading, Ctrl+C to stop
node src/cli.js run --once                                     # one tick, handy for cron
node src/cli.js --help
npm test
```

`run` wakes just after each candle closes, acts on it, and saves the paper account to
`cryptobot-state.json` (`--state` to change it), so restarting picks up where it left off.

Example backtest output:

```
BTC_USD 1h  2026-09-20 21:00 → 2026-10-31 08:00  (1000 candles)
  strategy return  -14.15%   (10000.00 → 8585.30)
  buy & hold       -4.57%
  max drawdown     14.15%
  round trips      16   win rate 18.8%   fees 302.97
```

That's a real result: the default parameters lost money over that window. Backtest before you
trust any setting, and remember that past performance doesn't predict future results.

## Layout

| File | Purpose |
| --- | --- |
| `src/exchange.js` | Candles (with pagination past the 300-per-call limit) and tickers |
| `src/indicators.js` | SMA, EMA, Wilder RSI |
| `src/strategy.js` | `decide(candles, position)` → buy / sell / hold |
| `src/paper.js` | Simulated account with fees and slippage |
| `src/backtest.js` | Replays history through the strategy and reports stats |
| `src/bot.js` | Live paper-trading loop with persisted state |
| `src/cli.js` | Command-line entry point |

To try another strategy, write a function with the same signature as `decide` in `strategy.js`.
