// Read-only market data from the Crypto.com Exchange public API (no API key needed).
const BASE = 'https://api.crypto.com/exchange/v1/public';
const MAX_PER_CALL = 300;

export const TIMEFRAME_MS = {
  '1m': 60e3, '5m': 300e3, '15m': 900e3, '30m': 1800e3,
  '1h': 3600e3, '2h': 7200e3, '4h': 14400e3, '12h': 43200e3,
  '1D': 86400e3, '7D': 604800e3,
};

async function call(method, params) {
  const url = `${BASE}/${method}?${new URLSearchParams(params)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${method} failed: HTTP ${res.status}`);
  const body = await res.json();
  if (body.code !== 0) throw new Error(`${method} failed: code ${body.code} ${body.message ?? ''}`);
  return body.result;
}

const toCandle = (c) => ({ t: c.t, o: +c.o, h: +c.h, l: +c.l, c: +c.c, v: +c.v });

/**
 * Fetch up to `limit` *closed* candles, oldest first, paginating backwards as needed.
 */
export async function getCandles(symbol, timeframe, limit = 300, { now = Date.now() } = {}) {
  const step = TIMEFRAME_MS[timeframe];
  if (!step) throw new Error(`Unsupported timeframe "${timeframe}". Use one of: ${Object.keys(TIMEFRAME_MS).join(', ')}`);

  const byTime = new Map();
  let endTs;
  while (byTime.size < limit) {
    const params = { instrument_name: symbol, timeframe, count: MAX_PER_CALL };
    if (endTs) params.end_ts = endTs;
    const { data = [] } = await call('get-candlestick', params);
    const before = byTime.size;
    for (const raw of data) byTime.set(raw.t, toCandle(raw));
    if (data.length === 0 || byTime.size === before) break; // no more history
    endTs = Math.min(...data.map((d) => d.t));
  }

  return [...byTime.values()]
    .filter((c) => c.t + step <= now) // drop the candle that is still forming
    .sort((a, b) => a.t - b.t)
    .slice(-limit);
}

export async function getTicker(symbol) {
  const { data } = await call('get-tickers', { instrument_name: symbol });
  const t = data?.[0];
  if (!t) throw new Error(`No ticker for ${symbol}`);
  return { symbol: t.i, last: +t.a, bid: +t.b, ask: +t.k, high24h: +t.h, low24h: +t.l, change24h: +t.c, volume24h: +t.v };
}
