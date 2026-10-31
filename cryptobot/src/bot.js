import { readFile, writeFile, rename } from 'node:fs/promises';
import { getCandles, TIMEFRAME_MS } from './exchange.js';
import { decide, warmup } from './strategy.js';
import { PaperAccount } from './paper.js';

async function loadState(file) {
  try { return JSON.parse(await readFile(file, 'utf8')); } catch (e) {
    if (e.code === 'ENOENT') return null;
    throw e;
  }
}

async function saveState(file, state) {
  await writeFile(`${file}.tmp`, JSON.stringify(state, null, 2));
  await rename(`${file}.tmp`, file);
}

/**
 * Live paper-trading loop. Acts once per newly closed candle; state survives restarts.
 */
export async function runBot({ symbol, timeframe, strategy, account, stateFile, once = false, log = console.log }) {
  const saved = await loadState(stateFile);
  if (saved && (saved.symbol !== symbol || saved.timeframe !== timeframe)) {
    throw new Error(`${stateFile} belongs to ${saved.symbol} ${saved.timeframe}; use another --state file or delete it.`);
  }
  const acct = new PaperAccount(account, saved?.account);
  let lastCandle = saved?.lastCandle ?? 0;
  const need = Math.max(warmup(strategy) + 50, 100);
  let stopping = false;
  const stop = () => { stopping = true; log('Stopping after current tick…'); };
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);

  log(`cryptobot (PAPER) ${symbol} ${timeframe} | cash ${acct.cash.toFixed(2)} | state ${stateFile}`);

  while (!stopping) {
    try {
      const candles = await getCandles(symbol, timeframe, need);
      const latest = candles.at(-1);
      if (latest && latest.t > lastCandle) {
        const { action, reason, indicators: ind } = decide(candles, acct.position, strategy);
        const fmt = (x) => (x == null ? '-' : x.toFixed(2));
        const stamp = new Date(latest.t + TIMEFRAME_MS[timeframe]).toISOString();
        log(`${stamp} price ${fmt(ind.price)} emaF ${fmt(ind.fast)} emaS ${fmt(ind.slow)} rsi ${fmt(ind.rsi)} -> ${action} (${reason})`);
        const trade = action === 'buy' ? acct.buy(latest.c, latest.t, reason)
          : action === 'sell' ? acct.sell(latest.c, latest.t, reason) : null;
        if (trade) log(`  ${trade.side.toUpperCase()} ${trade.qty.toFixed(6)} @ ${trade.price.toFixed(2)}${trade.pnl != null ? ` pnl ${trade.pnl.toFixed(2)}` : ''}`);
        log(`  equity ${acct.equity(latest.c).toFixed(2)} (start ${acct.startCash.toFixed(2)})`);
        lastCandle = latest.t;
        await saveState(stateFile, { symbol, timeframe, lastCandle, account: acct.toJSON() });
      }
    } catch (e) {
      log(`error: ${e.message} (retrying next tick)`);
    }
    if (once) break;
    // Wake shortly after the next candle closes.
    const step = TIMEFRAME_MS[timeframe];
    const wait = step - (Date.now() % step) + 5_000;
    await new Promise((r) => { const t = setTimeout(r, wait); const s = () => { clearTimeout(t); r(); }; process.once('SIGINT', s); process.once('SIGTERM', s); });
  }
  return acct;
}
