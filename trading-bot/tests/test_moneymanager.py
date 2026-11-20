import unittest

from moneymanager import (AssetClass, Bar, FixedFractionalRisk, FractionalKelly, Instrument, MoneyManager,
                          Order, Portfolio, RiskLimits, RiskManager, Side, Signal, VolatilityTarget)
from moneymanager.brokers import PaperBroker
from moneymanager.config import build_from_config
from moneymanager.engine import Engine, Market
from moneymanager.models import Fill
from moneymanager.strategy import TrendFollowing

STOCK = Instrument("AAPL", AssetClass.STOCK)
BTC = Instrument("BTC", AssetClass.CRYPTO, lot_size=0.0001, allow_short=True)
ES = Instrument("ES", AssetClass.FUTURES, multiplier=50, allow_short=True)


def fill(inst, side, qty, price):
    return Fill("2024-01-01", inst.symbol, side, qty, price, 0.0)


class TestInstrument(unittest.TestCase):
    def test_round_qty(self):
        self.assertEqual(STOCK.round_qty(12.9), 12)
        self.assertEqual(BTC.round_qty(0.123456), 0.1234)
        self.assertEqual(STOCK.round_qty(-3.7), -3)
        self.assertEqual(Instrument("X", AssetClass.STOCK, min_qty=5).round_qty(4), 0.0)


class TestSizing(unittest.TestCase):
    def test_fixed_fractional_risks_exact_amount(self):
        s = FixedFractionalRisk(0.01)
        qty = s.size(equity=100_000, instrument=STOCK, price=100, signal=Signal("AAPL", 1, stop_price=95),
                     volatility=None)
        self.assertAlmostEqual(qty * 5, 1000)  # 1% of 100k at $5 stop distance

    def test_fixed_fractional_respects_multiplier(self):
        s = FixedFractionalRisk(0.01)
        qty = s.size(equity=100_000, instrument=ES, price=5000, signal=Signal("ES", 1, stop_price=4980),
                     volatility=None)
        self.assertAlmostEqual(qty, 1.0)  # 20pt * $50 = $1000 per contract

    def test_vol_target(self):
        qty = VolatilityTarget(0.005).size(equity=100_000, instrument=STOCK, price=100,
                                           signal=Signal("AAPL", 1), volatility=2.0)
        self.assertAlmostEqual(qty, 250)

    def test_kelly_capped_and_nonnegative(self):
        self.assertEqual(FractionalKelly(0.3, 1.0).risk_fraction, 0.0)  # negative edge -> no bet
        self.assertEqual(FractionalKelly(0.9, 5.0, fraction=1.0, max_risk=0.02).risk_fraction, 0.02)

    def test_kelly_updates_from_trades(self):
        k = FractionalKelly(0.5, 1.0)
        k.update_from_trades([200] * 20 + [-100] * 20, min_trades=30)
        self.assertAlmostEqual(k.win_rate, 0.5)
        self.assertAlmostEqual(k.payoff_ratio, 2.0)


class TestPortfolio(unittest.TestCase):
    def test_round_trip_pnl(self):
        pf = Portfolio(10_000)
        pf.apply_fill(fill(STOCK, Side.BUY, 10, 100), STOCK)
        pf.mark("AAPL", 110)
        self.assertAlmostEqual(pf.equity, 10_100)
        pf.apply_fill(fill(STOCK, Side.SELL, 10, 110), STOCK)
        self.assertAlmostEqual(pf.cash, 10_100)
        self.assertEqual(pf.closed_trades, [100])

    def test_short_futures_pnl(self):
        pf = Portfolio(100_000)
        pf.apply_fill(fill(ES, Side.SELL, 2, 5000), ES)
        pf.mark("ES", 4990)
        self.assertAlmostEqual(pf.equity, 101_000)  # 10pt * 50 * 2

    def test_flip_position(self):
        pf = Portfolio(100_000)
        pf.apply_fill(fill(BTC, Side.BUY, 1, 100), BTC)
        pf.apply_fill(fill(BTC, Side.SELL, 3, 120), BTC, stop_price=130)
        pos = pf.positions["BTC"]
        self.assertAlmostEqual(pos.qty, -2)
        self.assertAlmostEqual(pos.avg_price, 120)
        self.assertEqual(pf.closed_trades, [20])

    def test_drawdown(self):
        pf = Portfolio(1000)
        pf.apply_fill(fill(STOCK, Side.BUY, 10, 100), STOCK)
        pf.record_equity("t1")
        pf.mark("AAPL", 80)
        self.assertAlmostEqual(pf.drawdown, 0.2)


class TestRisk(unittest.TestCase):
    def setUp(self):
        self.pf = Portfolio(100_000)

    def test_position_cap_shrinks_order(self):
        rm = RiskManager(RiskLimits(max_position_pct=0.10))
        d = rm.check(Order(STOCK, Side.BUY, 500), self.pf, 100)  # $50k wanted, $10k allowed
        self.assertEqual(d.approved_qty, 100)

    def test_no_short_on_stock(self):
        rm = RiskManager(RiskLimits())
        self.assertFalse(rm.check(Order(STOCK, Side.SELL, 10), self.pf, 100).approved)

    def test_class_cap(self):
        rm = RiskManager(RiskLimits(max_position_pct=1, class_caps={"crypto": 0.05}))
        d = rm.check(Order(BTC, Side.BUY, 1), self.pf, 50_000)
        self.assertAlmostEqual(d.approved_qty, 0.1)

    def test_open_risk_cap(self):
        rm = RiskManager(RiskLimits(max_position_pct=1, max_total_open_risk=0.02))
        d = rm.check(Order(STOCK, Side.BUY, 1000, stop_price=90), self.pf, 100)
        self.assertEqual(d.approved_qty, 200)  # $2000 risk / $10 per share

    def test_max_positions(self):
        rm = RiskManager(RiskLimits(max_positions=1))
        self.pf.apply_fill(fill(BTC, Side.BUY, 0.01, 50_000), BTC)
        self.assertFalse(rm.check(Order(STOCK, Side.BUY, 1), self.pf, 100).approved)

    def test_kill_switch_blocks_new_but_allows_exits(self):
        rm = RiskManager(RiskLimits(max_drawdown=0.1))
        self.pf.apply_fill(fill(STOCK, Side.BUY, 200, 100), STOCK)
        self.pf.record_equity("t")
        self.pf.mark("AAPL", 40)  # -12k -> 12% drawdown
        rm.update(self.pf)
        self.assertTrue(rm.halted)
        self.assertFalse(rm.check(Order(BTC, Side.BUY, 0.01), self.pf, 50_000).approved)
        self.assertTrue(rm.check(Order(STOCK, Side.SELL, 200), self.pf, 40).approved)

    def test_daily_loss_limit(self):
        rm = RiskManager(RiskLimits(daily_loss_limit=0.02))
        self.pf.apply_fill(fill(STOCK, Side.BUY, 100, 100), STOCK)
        self.pf.on_new_bar_time("2024-01-02")
        self.pf.mark("AAPL", 70)  # -3k = -3%
        self.assertFalse(rm.check(Order(BTC, Side.BUY, 0.01), self.pf, 50_000).approved)


class TestEngine(unittest.TestCase):
    def _bars(self, closes):
        return [Bar(f"2024-01-{i + 1:02d}" if i < 31 else f"2024-02-{i - 30:02d}", c, c * 1.01, c * 0.99, c)
                for i, c in enumerate(closes)]

    def _run(self, closes):
        pf = Portfolio(100_000)
        mm = MoneyManager(pf, FixedFractionalRisk(0.01), RiskManager(RiskLimits(max_position_pct=1)),
                          PaperBroker())
        Engine(mm, [Market(STOCK, self._bars(closes), TrendFollowing(5, 10, 5, 2.0, allow_short=False))]).run()
        return pf, mm

    def test_stop_loss_limits_loss(self):
        closes = [100 + i for i in range(30)] + [129 - 3 * i for i in range(1, 15)]  # up, then steady slide
        pf, mm = self._run(closes)
        self.assertTrue(any(e.kind == "stop" for e in mm.events))
        self.assertGreater(min(e for _, e in pf.equity_curve), 98_500)  # ~1% risk budget

    def test_gap_through_stop_fills_at_open(self):
        closes = [100 + i for i in range(30)] + [60]
        pf, mm = self._run(closes)
        stop_fill = pf.fills[-1]
        self.assertIn("stop", stop_fill.reason)
        self.assertAlmostEqual(stop_fill.price, 60)  # gap risk is real: filled at the open, not the stop

    def test_example_config_runs(self):
        import json, pathlib
        cfg = json.loads((pathlib.Path(__file__).parent.parent / "config.example.json").read_text())
        pf = build_from_config(cfg).run()
        self.assertGreater(len(pf.fills), 0)
        self.assertLess(pf.drawdown, cfg["risk"]["max_drawdown"] + 0.05)

    def test_live_broker_rejected_from_config(self):
        with self.assertRaises(ValueError):
            build_from_config({"broker": "ccxt", "markets": []})


if __name__ == "__main__":
    unittest.main()
