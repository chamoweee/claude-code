# Money Manager: a multi-market trading bot

A trading engine for **stocks, ETFs, crypto, forex and futures** that puts money management first.
Strategies only say *which way* to trade. The money manager decides *how much*, and every order has to pass a risk gate first.

> **Paper trading by default.** This is risk-management software, not a profit guarantee. The bundled
> strategies are simple examples. Backtest on real data, then paper trade, before risking any capital.

## Quick start (Python 3.10+, no dependencies)

```bash
cd trading-bot
python3 -m moneymanager backtest config.example.json            # 7 markets, synthetic data
python3 -m moneymanager backtest config.example.json -v --trades-csv fills.csv --equity-csv equity.csv
python3 -m unittest discover -s tests
```

## How an order flows

```
bar data ─► Strategy ─► Signal(direction, strength, stop)
                           │
                           ▼
            Sizer (equity × class allocation) ─► target qty, rounded to lot size
                           │
                           ▼
            RiskManager ─► approve / shrink / reject
                           │
                           ▼
            Broker (Paper | CCXT | your adapter) ─► Fill ─► Portfolio accounting
```

## Position sizing (`sizing`)
| type | what it does |
|---|---|
| `fixed_fractional` | Risks `risk_per_trade` of equity between entry and stop (default 1%). Works across markets because it uses each instrument's contract multiplier. |
| `volatility_target` | Sizes each position so it adds `target_vol_per_position` of equity in ATR volatility. |
| `kelly` | Fractional Kelly from win rate and payoff ratio, capped at `max_risk`. It can recalibrate from realized trades. |

## Risk limits (`risk`)
- `max_drawdown`: a **kill switch**. It flattens everything and blocks new risk until `RiskManager.reset()` is called.
- `daily_loss_limit`: no new trades for the rest of the day after this loss.
- `max_positions`, `max_position_pct`, `max_gross_leverage`
- `max_total_open_risk`: the sum of stop-distance risk across all positions.
- `class_caps`: gross exposure cap per asset class, e.g. `{"crypto": 0.30}`.
- `class_max_position_pct`: per-position cap by class, so futures and FX can use more leverage than stocks.
- Orders that reduce risk (exits, stops) are always allowed. Shorting is blocked unless the instrument sets `allow_short`.

Stops are checked on every bar against the high and low. A gap through the stop fills at the open, which is how real markets behave. Stops trail in the trade's favour when `trail_stops` is on.

`allocations` sets the share of equity each asset class sizes against. For example, `{"crypto": 0.5}` halves crypto position sizes.

## Markets
Each market in the config sets `symbol`, `asset_class`, `multiplier`, `lot_size`, `min_qty`, `allow_short`,
`commission_per_unit`, `commission_pct`, `slippage_pct`, `data` and optionally its own `strategy`.
For data, use `{"csv": "data/AAPL.csv"}` with date/open/high/low/close[/volume] columns, or `{"synthetic": {...}}`.

## Going live
The CLI only runs the paper broker. To trade live you have to wire in a broker deliberately:
- **Crypto:** `brokers/ccxt_broker.py` (`pip install ccxt`) covers 100+ exchanges. It refuses to trade unless you pass `live=True`
  **and** set `MONEYMANAGER_LIVE=1`. Keys come from the env vars `CCXT_API_KEY` and `CCXT_SECRET`, never from config files. It starts in sandbox mode.
- **Stocks, futures, FX:** subclass `brokers.base.Broker` and implement `submit()`. Alpaca, Interactive Brokers (`ib_insync`) and OANDA all fit this interface.

## Layout
```
moneymanager/
  models.py     Instrument, Bar, Order, Fill, Position, Signal
  sizing.py     position sizers
  risk.py       RiskLimits + RiskManager (the gate and kill switch)
  portfolio.py  cash, positions, P&L, drawdown, exposure
  engine.py     MoneyManager + multi-market Engine
  strategy.py   TrendFollowing, MeanReversion, ATR
  brokers/      PaperBroker, CCXTBroker, Broker interface
  report.py     CAGR, Sharpe, Sortino, max DD, win rate, profit factor
```
