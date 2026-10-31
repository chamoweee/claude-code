import { decide, warmup } from './strategy.js';
import { PaperAccount } from './paper.js';

export function backtest(candles, { strategy = {}, account = {} } = {}) {
  const acct = new PaperAccount(account);
  const start = warmup(strategy);
  if (candles.length <= start) throw new Error(`Need more than ${start} candles, got ${candles.length}`);

  let peak = acct.equity(candles[0].c);
  let maxDrawdown = 0;
  for (let i = start; i < candles.length; i++) {
    const window = candles.slice(0, i + 1);
    const { c: price, t } = candles[i];
    const { action, reason } = decide(window, acct.position, strategy);
    if (action === 'buy') acct.buy(price, t, reason);
    else if (action === 'sell') acct.sell(price, t, reason);

    const eq = acct.equity(price);
    peak = Math.max(peak, eq);
    maxDrawdown = Math.max(maxDrawdown, (peak - eq) / peak);
  }

  const first = candles[start].c;
  const last = candles.at(-1).c;
  const sells = acct.trades.filter((t) => t.side === 'sell');
  const wins = sells.filter((t) => t.pnl > 0).length;
  const finalEquity = acct.equity(last);
  return {
    from: candles[start].t,
    to: candles.at(-1).t,
    startEquity: acct.startCash,
    finalEquity,
    returnPct: (finalEquity / acct.startCash - 1) * 100,
    buyAndHoldPct: (last / first - 1) * 100,
    maxDrawdownPct: maxDrawdown * 100,
    roundTrips: sells.length,
    winRatePct: sells.length ? (wins / sells.length) * 100 : 0,
    feesPaid: acct.trades.reduce((s, t) => s + t.fee, 0),
    openPosition: acct.position,
    trades: acct.trades,
  };
}
