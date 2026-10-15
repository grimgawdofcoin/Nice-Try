from ..core.icc import ICCDetector, ICCParams
from ..core.indicators import atr, ema
from ..core.strategy import RiskConfig, Session, Signal, Strategy


class FiberPullback(Strategy):
    symbol = "EURUSD"
    name = "Fiber Deep Pullback"
    style = "ICC with deep 50-79% retracements, London-led"
    rationale = ("EURUSD is the most liquid pair, so it tends to retrace deeper and "
                 "more cleanly than other pairs. Shallow 38% entries get chopped up. "
                 "This bot waits for 50-79% pullbacks, only during London and the "
                 "London/NY overlap, and needs a rising (or falling) trend EMA. "
                 "Targets stay modest because EURUSD's range is small.")
    sessions = [Session("London", 7, 10.5), Session("Overlap", 12.5, 15)]
    risk = RiskConfig(risk_pct=0.01, max_signals_per_session=1, max_losses_per_day=2)
    spread = 0.00008
    params = ICCParams(lookback=16, impulse_atr=1.5, zone=(0.5, 0.786),
                       invalid=0.886, max_corr_bars=20)

    def prepare(self, df):
        df["atr"] = atr(df, 14)
        df["trend"] = ema(df["close"], 100)
        df["slope"] = df["trend"] - df["trend"].shift(8)
        self.icc = ICCDetector(self.params)
        return df

    def on_bar(self, i, df):
        r = df.iloc[i]
        for ev in self.icc.update(r.open, r.high, r.low, r.close, r.atr):
            if r.slope * ev.direction <= 0:
                continue
            stop = ev.corr_extreme - ev.direction * 0.1 * r.atr
            # Floor the stop at half an ATR so noise doesn't take it out.
            if abs(r.close - stop) < 0.5 * r.atr:
                stop = r.close - ev.direction * 0.5 * r.atr
            return Signal(ev.direction, stop, tp1_r=1.0, tp2_r=2.0, partial=0.5,
                          max_bars=32, reason=f"deep pullback {ev.retrace:.0%}")
        return None
