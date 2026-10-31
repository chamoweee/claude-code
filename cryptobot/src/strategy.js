import { ema, rsi } from './indicators.js';

export const DEFAULTS = {
  fast: 12,          // fast EMA period
  slow: 26,          // slow EMA period
  rsiPeriod: 14,
  rsiMaxEntry: 70,   // skip entries when RSI is above this (overbought)
  stopLoss: 0.03,    // exit if price falls 3% below entry
  takeProfit: 0.06,  // exit if price rises 6% above entry
};

/**
 * Decide what to do on the last closed candle.
 * @param candles closed candles, oldest first
 * @param position null or { entryPrice }
 * @returns { action: 'buy'|'sell'|'hold', reason, indicators }
 */
export function decide(candles, position, opts = {}) {
  const p = { ...DEFAULTS, ...opts };
  const closes = candles.map((c) => c.c);
  const i = closes.length - 1;
  const fast = ema(closes, p.fast);
  const slow = ema(closes, p.slow);
  const r = rsi(closes, p.rsiPeriod);
  const indicators = { price: closes[i], fast: fast[i], slow: slow[i], rsi: r[i] };

  if (i < 1 || fast[i - 1] == null || slow[i - 1] == null || r[i] == null) {
    return { action: 'hold', reason: 'warming up', indicators };
  }

  const crossedUp = fast[i - 1] <= slow[i - 1] && fast[i] > slow[i];
  const crossedDown = fast[i - 1] >= slow[i - 1] && fast[i] < slow[i];
  const price = closes[i];

  if (position) {
    const change = price / position.entryPrice - 1;
    if (change <= -p.stopLoss) return { action: 'sell', reason: `stop loss (${(change * 100).toFixed(2)}%)`, indicators };
    if (change >= p.takeProfit) return { action: 'sell', reason: `take profit (+${(change * 100).toFixed(2)}%)`, indicators };
    if (crossedDown) return { action: 'sell', reason: 'EMA cross down', indicators };
    return { action: 'hold', reason: 'in position', indicators };
  }

  if (crossedUp) {
    if (r[i] > p.rsiMaxEntry) return { action: 'hold', reason: `cross up but RSI ${r[i].toFixed(1)} overbought`, indicators };
    return { action: 'buy', reason: `EMA cross up, RSI ${r[i].toFixed(1)}`, indicators };
  }
  return { action: 'hold', reason: 'no signal', indicators };
}

/** Minimum candles needed before the strategy can produce signals. */
export const warmup = (opts = {}) => {
  const p = { ...DEFAULTS, ...opts };
  return Math.max(p.slow, p.rsiPeriod) + 2;
};
