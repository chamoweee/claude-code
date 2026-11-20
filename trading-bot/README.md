# Money Manager: an AI trading agent for every market

A trading engine for **stocks, ETFs, crypto, forex and futures** that puts money management first.
Strategies only say *which way* to trade. The money manager decides *how much*, and every order has to pass a risk gate first.

> **Paper trading by default.** This is risk-management software, not a profit guarantee. The bundled
> strategies are simple examples. Backtest on real data, then paper trade, before risking any capital.

## AI agent auto-trading

Claude acts as the portfolio manager. Each cycle (one new bar, e.g. hourly) the bot:
1. Pulls the latest closed bars for every market (Yahoo for stocks, ETFs, FX and futures; ccxt for any crypto exchange).
2. Sends Claude a snapshot of each market (returns, moving averages, ATR, RSI, recent closes, the current position) and the portfolio's risk state.
3. Claude can search the web for news if `web_search` is on, then calls a strict `submit_decisions` tool with `long` / `short` / `flat` / `hold`, a conviction from 0 to 1, and a stop for each market.
4. Each decision is checked: stops on the wrong side or at absurd distances get replaced, low conviction becomes `hold`, and unknown symbols or disallowed shorts are dropped.
5. The money manager sizes positions and runs the risk gate, stops and kill switch exactly as for any other strategy. **Claude never chooses quantities or bypasses limits.**
6. Fills go to `fills.jsonl`, Claude's reasoning to `ai_journal.jsonl`, and the portfolio to `bot_state.json`, so a restart picks up where it left off.

If the API fails, refuses, or doesn't answer properly, the bot holds its current positions and tries again next cycle.

```bash
pip install anthropic yfinance        # plus ccxt for crypto exchange data or live crypto trading
export ANTHROPIC_API_KEY=sk-ant-...   # or: ant auth login
python3 -m moneymanager trade config.ai.json --once -v   # one cycle, paper money
python3 -m moneymanager trade config.ai.json             # keep running; Ctrl+C to stop
```

`ai` settings: `model` (default `claude-opus-5-5`), `effort` (`low`…`max`, default `medium`), `web_search`,
`decide_every` (bars between AI calls), `min_conviction`, `warmup` (bars of history before the first decision),
`max_calls` (hard cap on API calls per run, to control cost), `journal`.
Requests use server-side refusal fallbacks (`fallbacks: "default"`), so if the model declines a cycle the API retries it on a fallback model.
To give a market a fixed rule-based strategy instead of the AI, set a `strategy` on that market.

`live` settings: `timeframe` (`1m`…`1d`), `history_bars`, `feed` (`{"type": "yahoo"}`, `{"type": "ccxt", "exchange": "kraken"}`
or `{"type": "synthetic"}`), plus a per-market `feed` and `feed_symbol` (e.g. `"ES=F"`, `"EURUSD=X"`, `"BTC-USD"`).

**Cost:** one API call per decision cycle covers all markets. Hourly bars around the clock is about 24 calls a day. Use `decide_every`, a longer `timeframe` or a lower `effort` to cut this.

**Backtesting the AI:** `backtest` works with `ai.enabled`, but every bar is an API call. Claude may also recognise real historical prices from its training data, so AI backtests on real history look better than live results will. Judge the agent by paper trading going forward.

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

## Going live with real money
Everything runs on paper by default. Real money takes three deliberate steps: a live `broker` in the config,
the `--live` flag, **and** `MONEYMANAGER_LIVE=1`. Paper trade for weeks first.
- Crypto: `"broker": {"type": "ccxt", "exchange": "kraken", "sandbox": false}` (all markets must be crypto).
  `python3 -m moneymanager trade config.json --live`. Keys come from `CCXT_API_KEY` and `CCXT_SECRET`.
  The bot doesn't yet reconcile its positions against the exchange's, so don't trade the same account by hand.

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
  engine.py     MoneyManager + multi-market Engine (step-by-step, for backtest and live)
  ai_agent.py   ClaudeTrader: the Claude portfolio-manager agent
  feeds.py      Yahoo, ccxt and synthetic live data
  live.py       AutoTrader polling loop
  state.py      save/restore portfolio across restarts
  strategy.py   TrendFollowing, MeanReversion, ATR
  brokers/      PaperBroker, CCXTBroker, Broker interface
  report.py     CAGR, Sharpe, Sortino, max DD, win rate, profit factor
```
