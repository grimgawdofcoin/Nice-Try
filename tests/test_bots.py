import os
import tempfile
import unittest

import pandas as pd

from bots import BOTS, backtest, get_bot
from bots.core.data import load_csv, synthetic
from bots.core.icc import ICCDetector, ICCParams
from bots.core.strategy import RiskConfig, Session, Signal, Strategy


def bars(rows, start="2024-01-02 08:00"):
    idx = pd.date_range(start, periods=len(rows), freq="15min", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 1.0
    return df


class Scripted(Strategy):
    """Fires pre-set signals at given bar indexes."""
    symbol = "TEST"
    sessions = [Session("Day", 0, 24)]
    risk = RiskConfig(risk_pct=0.01, max_signals_per_session=10, max_losses_per_day=2,
                      one_per_direction=False)

    def __init__(self, plan):
        self.plan = plan

    def prepare(self, df):
        df["atr"] = 1.0
        return df

    def on_bar(self, i, df):
        return self.plan.get(i)


class EngineTests(unittest.TestCase):
    def test_fills_next_open_and_sizes_by_risk(self):
        df = bars([(100, 100, 100, 100), (101, 101, 101, 101), (101, 101, 101, 101)])
        res = backtest(Scripted({0: Signal(1, 99, tp2_r=5)}), df, 10_000)
        t = res.trades[0]
        self.assertEqual(t.entry, 101)        # next bar's open, not the signal close
        self.assertAlmostEqual(t.initial_size * 2, 100)  # $100 risk / $2 stop distance

    def test_stop_wins_when_bar_hits_both(self):
        df = bars([(100, 100, 100, 100), (100, 103, 98, 100)])
        res = backtest(Scripted({0: Signal(1, 99, tp1_r=1, tp2_r=2)}), df)
        self.assertEqual(res.trades[0].exit_reason, "stop")
        self.assertAlmostEqual(res.trades[0].r, -1.0)

    def test_tp1_partial_then_breakeven(self):
        df = bars([(100, 100, 100, 100), (100, 101.5, 100, 101), (101, 101, 99.5, 100)])
        res = backtest(Scripted({0: Signal(1, 99, tp1_r=1, tp2_r=3, partial=0.5)}), df)
        t = res.trades[0]
        self.assertTrue(t.tp1_hit)
        self.assertEqual(t.exit_reason, "breakeven")
        self.assertAlmostEqual(t.r, 0.5)

    def test_gap_through_stop_fills_at_open(self):
        df = bars([(100, 100, 100, 100), (100, 100, 100, 100), (97, 97, 96, 96)])
        res = backtest(Scripted({0: Signal(1, 99, tp2_r=5)}), df)
        self.assertAlmostEqual(res.trades[0].r, -3.0)

    def test_daily_loss_limit(self):
        rows = [(100, 100, 100, 100), (100, 100, 98, 99)] * 4
        plan = {0: Signal(1, 99), 2: Signal(1, 99), 4: Signal(1, 99), 6: Signal(1, 99)}
        res = backtest(Scripted(plan), bars(rows))
        self.assertEqual(len(res.trades), 2)  # done after 2 losses in a day

    def test_session_filter(self):
        s = Scripted({})
        s.sessions = [Session("London", 7, 11)]
        self.assertEqual(s.session_of(pd.Timestamp("2024-01-02 08:00", tz="UTC")), "London")
        self.assertIsNone(s.session_of(pd.Timestamp("2024-01-02 12:00", tz="UTC")))
        self.assertIsNone(s.session_of(pd.Timestamp("2024-01-06 08:00", tz="UTC")))  # Saturday


class ICCTests(unittest.TestCase):
    def run_series(self, rows, p):
        det = ICCDetector(p)
        out = []
        for o, h, l, c in rows:
            out += det.update(o, h, l, c, 1.0)
        return out

    def test_long_continuation_found(self):
        p = ICCParams(lookback=3, impulse_atr=2, zone=(0.38, 0.62), invalid=0.79, max_corr_bars=10)
        rows = [(10, 10.5, 9.5, 10)] * 3 + [
            (10, 14, 10, 14),       # indication: breaks structure, 4.5 ATR leg
            (14, 14, 12.5, 12.6),   # correction ~33%
            (12.6, 12.7, 11.8, 12),  # ~49%, inside the AOI
            (12, 13, 11.9, 12.9),   # continuation: bullish, closes above prior high
        ]
        ev = self.run_series(rows, p)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].direction, 1)
        self.assertEqual(ev[0].corr_extreme, 11.8)

    def test_too_deep_is_a_reversal(self):
        p = ICCParams(lookback=3, impulse_atr=2, zone=(0.38, 0.62), invalid=0.79, max_corr_bars=10)
        rows = [(10, 10.5, 9.5, 10)] * 3 + [
            (10, 14, 10, 14), (14, 14, 10.2, 10.3), (10.3, 11.5, 10.2, 11.4)]
        self.assertEqual(self.run_series(rows, p), [])

    def test_short_is_mirror(self):
        p = ICCParams(lookback=3, impulse_atr=2, zone=(0.38, 0.62), invalid=0.79, max_corr_bars=10)
        rows = [(10, 10.5, 9.5, 10)] * 3 + [
            (10, 10, 6, 6), (6, 7.5, 6, 7.4), (7.4, 8.2, 7.3, 8), (8, 8.1, 7, 7.1)]
        ev = self.run_series(rows, p)
        self.assertEqual([e.direction for e in ev], [-1])
        self.assertEqual(ev[0].corr_extreme, 8.2)


class BotTests(unittest.TestCase):
    def test_every_bot_runs_and_obeys_its_rules(self):
        for sym in BOTS:
            bot = get_bot(sym)
            res = backtest(bot, synthetic(sym, days=60, seed=3))
            for t in res.trades:
                self.assertIsNotNone(bot.session_of(t.entry_time), f"{sym} traded off-session")
                self.assertGreaterEqual(t.r, -3.5, f"{sym} lost far more than 1R")
            per_day = pd.Series([t.entry_time.date() for t in res.trades]).value_counts()
            cap = bot.risk.max_signals_per_session * max(1, len(bot.sessions))
            self.assertTrue((per_day <= cap).all(), sym)

    def test_bots_differ(self):
        styles = {get_bot(s).style for s in BOTS}
        self.assertEqual(len(styles), len(BOTS))

    def test_nas_never_holds_overnight(self):
        res = backtest(get_bot("NAS100"), synthetic("NAS100", days=60, seed=5))
        for t in res.trades:
            self.assertEqual(t.entry_time.date(), t.exit_time.date())


class DataTests(unittest.TestCase):
    def test_load_mt5_style_csv(self):
        csv = "<DATE>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\n" + "\n".join(
            f"2024-01-02 08:{m:02d}:00\t1\t2\t0.5\t1.5\t10" for m in range(0, 30, 5))
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(csv)
        try:
            df = load_csv(f.name, "15min")
        finally:
            os.unlink(f.name)
        self.assertEqual(len(df), 2)
        self.assertEqual(df["volume"].iloc[0], 30)


if __name__ == "__main__":
    unittest.main()
