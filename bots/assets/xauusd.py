from ..core.icc import ICCDetector, ICCParams
from ..core.indicators import atr, ema
from ..core.strategy import RiskConfig, Session, Signal, Strategy


class GoldSweep(Strategy):
    symbol = "XAUUSD"
    name = "Gold Sweep"
    style = "ICC continuation after a liquidity sweep"
    rationale = ("Gold hunts stops before it moves. This bot only takes a continuation "
                 "after the correction has swept nearby lows/highs and reclaimed them, "
                 "trades with the higher-timeframe trend, and uses a wide stop "
                 "buffer for gold's wicks.")
    sessions = [Session("London", 7, 11), Session("NY", 12.5, 16)]
    risk = RiskConfig(risk_pct=0.01, max_signals_per_session=2, max_losses_per_day=2)
    spread = 0.30
    params = ICCParams(lookback=20, impulse_atr=2.0, zone=(0.382, 0.618),
                       invalid=0.786, max_corr_bars=24)

    def prepare(self, df):
        df["atr"] = atr(df, 14)
        df["bias"] = ema(df["close"], 200)  # ~2 days of 15m bars = HTF trend
        self.icc = ICCDetector(self.params)
        return df

    def on_bar(self, i, df):
        r = df.iloc[i]
        events = self.icc.update(r.open, r.high, r.low, r.close, r.atr)
        for ev in events:
            if not ev.swept:
                continue
            if (r.close - r.bias) * ev.direction <= 0:
                continue  # never fight the HTF
            stop = ev.corr_extreme - ev.direction * 0.25 * r.atr
            return Signal(ev.direction, stop, tp1_r=1.0, tp2_r=3.0, partial=0.5,
                          max_bars=48, reason=f"sweep+reclaim, retrace {ev.retrace:.0%}")
        return None
