import test from 'node:test';
import assert from 'node:assert/strict';
import { sma, ema, rsi } from '../src/indicators.js';

test('sma', () => {
  assert.deepEqual(sma([1, 2, 3, 4, 5], 3), [null, null, 2, 3, 4]);
});

test('ema seeds with sma and tracks a constant series', () => {
  const out = ema([5, 5, 5, 5, 5], 3);
  assert.deepEqual(out, [null, null, 5, 5, 5]);
  const rising = ema([1, 2, 3, 4], 3);
  assert.equal(rising[2], 2);
  assert.equal(rising[3], 3); // 4*0.5 + 2*0.5
});

test('rsi extremes', () => {
  const up = Array.from({ length: 30 }, (_, i) => i);
  assert.equal(rsi(up, 14).at(-1), 100);
  const down = up.map((x) => -x);
  assert.equal(rsi(down, 14).at(-1), 0);
  assert.equal(rsi(up, 14)[13], null);
});
