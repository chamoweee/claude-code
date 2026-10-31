import test from 'node:test';
import assert from 'node:assert/strict';
import { decide } from '../src/strategy.js';
import { PaperAccount } from '../src/paper.js';
import { backtest } from '../src/backtest.js';

const candles = (closes) => closes.map((c, i) => ({ t: i * 3600e3, o: c, h: c, l: c, c, v: 1 }));
const opts = { fast: 3, slow: 6, rsiPeriod: 5, rsiMaxEntry: 101 };

test('buys on a bullish EMA cross', () => {
  const closes = [...Array(20).fill(100).map((x, i) => x - i), 85, 95];
  assert.equal(decide(candles(closes), null, opts).action, 'buy');
});

test('stop loss and take profit', () => {
  const c = candles(Array(20).fill(100));
  assert.equal(decide(c, { entryPrice: 110 }, opts).action, 'sell');
  assert.equal(decide(c, { entryPrice: 90 }, opts).action, 'sell');
  assert.equal(decide(c, { entryPrice: 100 }, opts).action, 'hold');
});

test('warming up holds', () => {
  assert.equal(decide(candles([1, 2, 3]), null, opts).reason, 'warming up');
});

test('paper account round trip accounts for fees', () => {
  const a = new PaperAccount({ cash: 1000, feeRate: 0.01, slippage: 0 });
  a.buy(100, 0);
  assert.ok(Math.abs(a.position.qty - 9.9) < 1e-9);
  const t = a.sell(100, 1);
  assert.ok(Math.abs(a.cash - 980.1) < 1e-9);
  assert.ok(Math.abs(t.pnl - (980.1 - 1000)) < 1e-9);
  assert.equal(a.sell(100, 2), null);
});

test('backtest produces consistent stats', () => {
  const closes = Array.from({ length: 300 }, (_, i) => 100 + 10 * Math.sin(i / 8) + i * 0.05);
  const r = backtest(candles(closes), { strategy: opts, account: { cash: 1000 } });
  assert.ok(r.roundTrips > 0);
  const realized = r.trades.filter((t) => t.pnl != null).reduce((s, t) => s + t.pnl, 0);
  if (!r.openPosition) assert.ok(Math.abs(r.finalEquity - 1000 - realized) < 1e-6);
});
