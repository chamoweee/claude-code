"""Auto-trading loop: poll data feeds, let the strategy or AI decide, execute, save state, repeat."""
from __future__ import annotations

import json
import logging
import signal
import time
from pathlib import Path

from .engine import Engine
from .feeds import TIMEFRAME_SECONDS, Feed, build_feed
from .models import Bar
from .state import load_state, save_state

log = logging.getLogger("moneymanager.live")


class AutoTrader:
    def __init__(self, engine: Engine, feeds: dict[str, Feed], feed_symbols: dict[str, str],
                 timeframe: str = "1h", history_bars: int = 250, state_path: str | Path = "bot_state.json",
                 fills_log: str | Path = "fills.jsonl"):
        self.engine = engine
        self.feeds = feeds
        self.feed_symbols = feed_symbols
        self.timeframe = timeframe
        self.history_bars = history_bars
        self.state_path = Path(state_path)
        self.fills_log = Path(fills_log)
        self.last_seen: dict[str, str] = load_state(engine, self.state_path)
        self._warmed = False
        self._stop = False
        self._fills_written = len(engine.mm.portfolio.fills)

    def _fetch(self, sym: str) -> list[Bar]:
        try:
            return self.feeds[sym].fetch(self.feed_symbols[sym], self.timeframe, self.history_bars)
        except Exception as e:  # one market's outage shouldn't stop the others
            log.error("data fetch failed for %s: %s", sym, e)
            return []

    def cycle(self) -> int:
        """Run one polling cycle. Returns the number of new bars processed."""
        fresh: dict[str, list[Bar]] = {}
        for sym in self.engine.markets:
            bars = self._fetch(sym)
            if not bars:
                continue
            if not self._warmed:
                # Load history without trading on it, so indicators are ready from the first live bar.
                seen = self.last_seen.get(sym)
                warm = [b for b in bars if seen is None or b.timestamp <= seen]
                if seen is None:
                    warm, bars = bars[:-1], bars[-1:]
                self.engine.history[sym] = warm
                if warm:
                    self.last_seen.setdefault(sym, warm[-1].timestamp)
                    self.engine.mm.portfolio.mark(sym, warm[-1].close)
            seen = self.last_seen.get(sym, "")
            fresh[sym] = [b for b in bars if b.timestamp > seen]
        self._warmed = True

        by_ts: dict[str, dict[str, Bar]] = {}
        for sym, bars in fresh.items():
            for b in bars:
                by_ts.setdefault(b.timestamp, {})[sym] = b
        for ts in sorted(by_ts):
            self.engine.step(ts, by_ts[ts])
            for sym in by_ts[ts]:
                self.last_seen[sym] = ts
        self._log_fills()
        save_state(self.engine, self.state_path, self.last_seen)
        pf = self.engine.mm.portfolio
        log.warning("cycle done: %d new bars | equity %.2f | drawdown %.1f%% | %d open positions%s",
                    len(by_ts), pf.equity, pf.drawdown * 100, len(pf.open_positions()),
                    " | KILL SWITCH ON" if self.engine.mm.risk.halted else "")
        return len(by_ts)

    def _log_fills(self) -> None:
        fills = self.engine.mm.portfolio.fills[self._fills_written:]
        if fills:
            with open(self.fills_log, "a") as f:
                for fl in fills:
                    f.write(json.dumps({"time": fl.timestamp, "symbol": fl.symbol, "side": fl.side.value,
                                        "qty": fl.qty, "price": fl.price, "commission": fl.commission,
                                        "reason": fl.reason}) + "\n")
            self._fills_written += len(fills)

    def run_forever(self, poll_seconds: float | None = None) -> None:
        poll = poll_seconds or max(30, TIMEFRAME_SECONDS.get(self.timeframe, 3600) // 4)
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "_stop", True))
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "_stop", True))
        log.warning("auto-trading started: timeframe %s, polling every %ss, broker=%s. Ctrl+C to stop.",
                    self.timeframe, poll, self.engine.mm.broker.name)
        while not self._stop:
            self.cycle()
            for _ in range(int(poll)):
                if self._stop:
                    break
                time.sleep(1)
        log.warning("stopped; state saved to %s", self.state_path)


def build_autotrader(engine: Engine, cfg: dict, base_dir: Path) -> AutoTrader:
    live_cfg = cfg.get("live", {})
    default_feed = live_cfg.get("feed", {"type": "synthetic"})
    feeds, feed_symbols, shared = {}, {}, {}
    for i, m in enumerate(cfg["markets"]):
        fcfg = dict(m.get("feed", default_feed))
        if fcfg.get("type") == "synthetic":
            fcfg.setdefault("seed", i + 1)
            fcfg.setdefault("start_price", m.get("data", {}).get("synthetic", {}).get("start_price", 100.0))
            feeds[m["symbol"]] = build_feed(fcfg)
        else:
            key = json.dumps(fcfg, sort_keys=True)  # reuse one connection per exchange
            if key not in shared:
                shared[key] = build_feed(fcfg)
            feeds[m["symbol"]] = shared[key]
        feed_symbols[m["symbol"]] = m.get("feed_symbol", m["symbol"])
    return AutoTrader(engine, feeds, feed_symbols,
                      timeframe=live_cfg.get("timeframe", "1h"),
                      history_bars=live_cfg.get("history_bars", 250),
                      state_path=base_dir / live_cfg.get("state_file", "bot_state.json"),
                      fills_log=base_dir / live_cfg.get("fills_log", "fills.jsonl"))
