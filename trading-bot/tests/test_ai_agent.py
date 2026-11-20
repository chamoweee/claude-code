import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from moneymanager.ai_agent import ClaudeTrader
from moneymanager.config import build_from_config
from moneymanager.data import synthetic
from moneymanager.live import build_autotrader


def tool_response(decisions, view="test view"):
    block = SimpleNamespace(type="tool_use", name="submit_decisions",
                            input={"market_view": view, "decisions": decisions})
    return SimpleNamespace(stop_reason="tool_use", content=[block], model="claude-opus-5-5",
                           usage=SimpleNamespace(input_tokens=100, output_tokens=50))


class FakeClient:
    """Stands in for anthropic.Anthropic(). `script(request) -> response` decides what Claude says."""

    def __init__(self, script):
        self.requests = []
        self.script = script
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        return self.script(kw)


def snapshot_of(request):
    text = request["messages"][0]["content"]
    return json.loads(text[text.index("{"):])


def go_long_everything(request):
    snap = snapshot_of(request)
    return tool_response([{"symbol": m["symbol"], "action": "long", "conviction": 0.8,
                           "stop_price": m["price"] - 3 * m["atr_14"], "reasoning": "uptrend"}
                          for m in snap["markets"]])


CFG = {
    "starting_cash": 100000,
    "ai": {"enabled": True, "warmup": 30, "journal": None, "decide_every": 5},
    "risk": {"max_position_pct": 0.2},
    "markets": [
        {"symbol": "AAPL", "asset_class": "stock", "data": {"synthetic": {"n": 80, "start_price": 150}}},
        {"symbol": "BTC", "asset_class": "crypto", "lot_size": 0.0001, "allow_short": True,
         "data": {"synthetic": {"n": 80, "start_price": 60000, "vol": 0.03}}},
    ],
}


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.ai = ClaudeTrader(client=FakeClient(lambda r: None), journal=None, min_conviction=0.3)
        from moneymanager.models import AssetClass, Instrument
        self.inst = {"AAPL": Instrument("AAPL", AssetClass.STOCK),
                     "BTC": Instrument("BTC", AssetClass.CRYPTO, allow_short=True)}
        self.hist = {"AAPL": synthetic(100, 40, seed=1), "BTC": synthetic(100, 40, seed=2)}

    def test_bad_stop_replaced(self):
        price = self.hist["AAPL"][-1].close
        sigs, notes = self.ai.to_signals([{"symbol": "AAPL", "action": "long", "conviction": 0.9,
                                           "stop_price": price * 1.1, "reasoning": "x"}], self.hist, self.inst)
        self.assertLess(sigs["AAPL"].stop_price, price)
        self.assertTrue(any("invalid" in n for n in notes))

    def test_short_not_allowed_becomes_flat(self):
        sigs, _ = self.ai.to_signals([{"symbol": "AAPL", "action": "short", "conviction": 0.9,
                                       "stop_price": 0, "reasoning": "x"}], self.hist, self.inst)
        self.assertEqual(sigs["AAPL"].direction, 0)

    def test_low_conviction_and_hold_and_unknown_skipped(self):
        sigs, _ = self.ai.to_signals([
            {"symbol": "AAPL", "action": "long", "conviction": 0.1, "stop_price": 0, "reasoning": ""},
            {"symbol": "BTC", "action": "hold", "conviction": 1, "stop_price": 0, "reasoning": ""},
            {"symbol": "DOGE", "action": "long", "conviction": 1, "stop_price": 0, "reasoning": ""},
        ], self.hist, self.inst)
        self.assertEqual(sigs, {})

    def test_conviction_clamped(self):
        price = self.hist["BTC"][-1].close
        sigs, _ = self.ai.to_signals([{"symbol": "BTC", "action": "short", "conviction": 7,
                                       "stop_price": price * 1.05, "reasoning": ""}], self.hist, self.inst)
        self.assertEqual(sigs["BTC"].strength, 1.0)
        self.assertEqual(sigs["BTC"].direction, -1)


class TestAgentInEngine(unittest.TestCase):
    def test_ai_decisions_are_traded_through_risk_gate(self):
        client = FakeClient(go_long_everything)
        engine = build_from_config(CFG, ai_client=client)
        pf = engine.run()
        self.assertTrue(client.requests)
        req = client.requests[0]
        self.assertEqual(req["model"], "claude-opus-5-5")
        self.assertEqual(req["tools"][0]["name"], "submit_decisions")
        self.assertTrue(req["tools"][0]["strict"])
        self.assertEqual(req["tool_choice"], {"type": "auto"})
        self.assertGreater(len(pf.fills), 0)
        for p in pf.open_positions():  # the 20% position cap still applies to AI trades
            self.assertLessEqual(p.notional, 0.2 * pf.equity * 1.15)

    def test_api_failure_holds_instead_of_crashing(self):
        def boom(_):
            raise ConnectionError("network down")
        engine = build_from_config(CFG, ai_client=FakeClient(boom))
        pf = engine.run()
        self.assertEqual(pf.fills, [])

    def test_refusal_and_missing_tool_call_hold(self):
        for resp in (SimpleNamespace(stop_reason="refusal", content=[], usage=None),
                     SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="hm")],
                                     usage=None)):
            engine = build_from_config(CFG, ai_client=FakeClient(lambda r, resp=resp: resp))
            self.assertEqual(engine.run().fills, [])

    def test_call_budget(self):
        client = FakeClient(go_long_everything)
        cfg = json.loads(json.dumps(CFG))
        cfg["ai"]["max_calls"] = 2
        build_from_config(cfg, ai_client=client).run()
        self.assertEqual(len(client.requests), 2)

    def test_web_search_tool_and_pause_turn(self):
        calls = []

        def script(req):
            calls.append(req)
            if len(calls) == 1:
                return SimpleNamespace(stop_reason="pause_turn", content=[], usage=None)
            return go_long_everything(req)
        cfg = json.loads(json.dumps(CFG))
        cfg["ai"].update(web_search=True, max_calls=1)
        build_from_config(cfg, ai_client=FakeClient(script)).run()
        self.assertEqual(calls[0]["tools"][1]["type"], "web_search_20260209")
        self.assertEqual(len(calls), 2)  # resumed after pause_turn
        self.assertEqual(calls[1]["messages"][-1]["role"], "assistant")


class TestAutoTrader(unittest.TestCase):
    def test_cycles_persist_state_across_restart(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = json.loads(json.dumps(CFG))
            cfg["ai"]["decide_every"] = 1
            cfg["live"] = {"timeframe": "1h", "history_bars": 60, "feed": {"type": "synthetic"}}
            base = Path(d)
            engine = build_from_config(cfg, base, ai_client=FakeClient(go_long_everything))
            bot = build_autotrader(engine, cfg, base)
            for _ in range(3):
                self.assertEqual(bot.cycle(), 1)
            self.assertTrue(engine.mm.portfolio.open_positions())
            state = json.loads((base / "bot_state.json").read_text())
            self.assertTrue(state["positions"])
            self.assertTrue((base / "fills.jsonl").exists())

            engine2 = build_from_config(cfg, base, ai_client=FakeClient(go_long_everything))
            bot2 = build_autotrader(engine2, cfg, base)
            self.assertEqual(set(engine2.mm.portfolio.positions), set(state["positions"]))
            self.assertAlmostEqual(engine2.mm.portfolio.cash, state["cash"])
            self.assertEqual(bot2.last_seen, state["last_seen"])

    def test_live_broker_requires_flag(self):
        cfg = json.loads(json.dumps(CFG))
        cfg["broker"] = {"type": "ccxt", "exchange": "kraken"}
        with self.assertRaises(ValueError):
            build_from_config(cfg, ai_client=FakeClient(go_long_everything))


if __name__ == "__main__":
    unittest.main()
