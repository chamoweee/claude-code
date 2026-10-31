#!/usr/bin/env node
import { parseArgs } from 'node:util';
import { getCandles, getTicker } from './exchange.js';
import { backtest } from './backtest.js';
import { runBot } from './bot.js';
import { DEFAULTS } from './strategy.js';

const USAGE = `cryptobot — paper-trading bot (EMA crossover + RSI filter), Crypto.com market data

Usage:
  cryptobot price    [--symbol BTC_USD]
  cryptobot backtest [--symbol BTC_USD] [--timeframe 1h] [--candles 1000] [--trades]
  cryptobot run      [--symbol BTC_USD] [--timeframe 1h] [--state cryptobot-state.json] [--once]

Options:
  --symbol       instrument, e.g. BTC_USD, ETH_USD, SOL_USD   (default BTC_USD)
  --timeframe    1m 5m 15m 30m 1h 2h 4h 12h 1D 7D            (default 1h)
  --candles      history length for backtests                 (default 1000)
  --cash         starting paper cash                          (default 10000)
  --fee          fee rate per fill                            (default 0.001)
  --size         fraction of cash per entry, 0-1              (default 1)
  --fast --slow --rsi-period --rsi-max   strategy parameters  (default ${DEFAULTS.fast}/${DEFAULTS.slow}/${DEFAULTS.rsiPeriod}/${DEFAULTS.rsiMaxEntry})
  --stop-loss --take-profit              fractions, e.g. 0.03 (default ${DEFAULTS.stopLoss}/${DEFAULTS.takeProfit})
  --trades       print every backtest trade
  --once         run a single live tick and exit

No real orders are ever placed.`;

const { values: a, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    symbol: { type: 'string', default: 'BTC_USD' },
    timeframe: { type: 'string', default: '1h' },
    candles: { type: 'string', default: '1000' },
    cash: { type: 'string', default: '10000' },
    fee: { type: 'string', default: '0.001' },
    size: { type: 'string', default: '1' },
    fast: { type: 'string' }, slow: { type: 'string' },
    'rsi-period': { type: 'string' }, 'rsi-max': { type: 'string' },
    'stop-loss': { type: 'string' }, 'take-profit': { type: 'string' },
    state: { type: 'string', default: 'cryptobot-state.json' },
    trades: { type: 'boolean', default: false },
    once: { type: 'boolean', default: false },
    help: { type: 'boolean', short: 'h', default: false },
  },
});

const num = (v, name) => {
  if (v === undefined) return undefined;
  const n = Number(v);
  if (!Number.isFinite(n)) throw new Error(`--${name} must be a number`);
  return n;
};
const strategy = Object.fromEntries(Object.entries({
  fast: num(a.fast, 'fast'), slow: num(a.slow, 'slow'),
  rsiPeriod: num(a['rsi-period'], 'rsi-period'), rsiMaxEntry: num(a['rsi-max'], 'rsi-max'),
  stopLoss: num(a['stop-loss'], 'stop-loss'), takeProfit: num(a['take-profit'], 'take-profit'),
}).filter(([, v]) => v !== undefined));
const account = { cash: num(a.cash, 'cash'), feeRate: num(a.fee, 'fee'), positionSize: num(a.size, 'size') };
if ((strategy.fast ?? DEFAULTS.fast) >= (strategy.slow ?? DEFAULTS.slow)) throw new Error('--fast must be smaller than --slow');
if (!(account.positionSize > 0 && account.positionSize <= 1)) throw new Error('--size must be in (0, 1]');

const symbol = a.symbol.toUpperCase();
const date = (t) => new Date(t).toISOString().replace('T', ' ').slice(0, 16);

const [cmd] = positionals;
if (a.help || !cmd) { console.log(USAGE); process.exit(cmd || a.help ? 0 : 1); }

if (cmd === 'price') {
  const t = await getTicker(symbol);
  console.log(`${t.symbol}  last ${t.last}  bid ${t.bid}  ask ${t.ask}  24h ${(t.change24h * 100).toFixed(2)}%  range ${t.low24h}–${t.high24h}`);
} else if (cmd === 'backtest') {
  const candles = await getCandles(symbol, a.timeframe, num(a.candles, 'candles'));
  const r = backtest(candles, { strategy, account });
  if (a.trades) for (const t of r.trades) {
    console.log(`${date(t.time)}  ${t.side.padEnd(4)} ${t.price.toFixed(2).padStart(12)}  ${t.pnl != null ? `pnl ${t.pnl.toFixed(2).padStart(9)}` : ''.padEnd(13)}  ${t.reason}`);
  }
  console.log(`\n${symbol} ${a.timeframe}  ${date(r.from)} → ${date(r.to)}  (${candles.length} candles)`);
  console.log(`  strategy return  ${r.returnPct.toFixed(2)}%   (${r.startEquity.toFixed(2)} → ${r.finalEquity.toFixed(2)})`);
  console.log(`  buy & hold       ${r.buyAndHoldPct.toFixed(2)}%`);
  console.log(`  max drawdown     ${r.maxDrawdownPct.toFixed(2)}%`);
  console.log(`  round trips      ${r.roundTrips}   win rate ${r.winRatePct.toFixed(1)}%   fees ${r.feesPaid.toFixed(2)}`);
  if (r.openPosition) console.log(`  open position    ${r.openPosition.qty.toFixed(6)} @ ${r.openPosition.entryPrice.toFixed(2)}`);
} else if (cmd === 'run') {
  await runBot({ symbol, timeframe: a.timeframe, strategy, account, stateFile: a.state, once: a.once });
} else {
  console.error(`Unknown command "${cmd}"\n\n${USAGE}`);
  process.exit(1);
}
