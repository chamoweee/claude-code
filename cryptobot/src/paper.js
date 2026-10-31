// Simulated broker: no real orders are ever sent.
export class PaperAccount {
  constructor({ cash = 10_000, feeRate = 0.001, slippage = 0.0005, positionSize = 1 } = {}, state) {
    Object.assign(this, { feeRate, slippage, positionSize });
    this.cash = state?.cash ?? cash;
    this.startCash = state?.startCash ?? cash;
    this.position = state?.position ?? null; // { qty, entryPrice, entryTime }
    this.trades = state?.trades ?? [];
  }

  buy(price, time, reason = '') {
    if (this.position) return null;
    const fill = price * (1 + this.slippage);
    const spend = this.cash * this.positionSize;
    const fee = spend * this.feeRate;
    const qty = (spend - fee) / fill;
    if (qty <= 0) return null;
    this.cash -= spend;
    this.position = { qty, entryPrice: fill, entryTime: time };
    const trade = { side: 'buy', time, price: fill, qty, fee, reason };
    this.trades.push(trade);
    return trade;
  }

  sell(price, time, reason = '') {
    if (!this.position) return null;
    const fill = price * (1 - this.slippage);
    const gross = this.position.qty * fill;
    const fee = gross * this.feeRate;
    const cost = this.position.qty * this.position.entryPrice;
    const pnl = gross - fee - cost / (1 - this.feeRate); // include the entry fee
    this.cash += gross - fee;
    const trade = { side: 'sell', time, price: fill, qty: this.position.qty, fee, pnl, reason };
    this.trades.push(trade);
    this.position = null;
    return trade;
  }

  equity(price) {
    return this.cash + (this.position ? this.position.qty * price : 0);
  }

  toJSON() {
    const { cash, startCash, position, trades } = this;
    return { cash, startCash, position, trades };
  }
}
