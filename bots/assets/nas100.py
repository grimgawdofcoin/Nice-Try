from ..core.indicators import atr, session_vwap
from ..core.strategy import RiskConfig, Session, Signal, Strategy


class OpeningDrive(Strategy):
    symbol = "NAS100"
    name = "NAS Opening Drive"
    style = "NY opening-range break, pullback to range/VWAP, flat by the close"
    rationale = ("Nasdaq does most of its real moving after the 9:30 ET cash open. "
                 "This bot marks the first 30 minutes as the opening range, treats "
                 "the break as the Indication, waits for a pullback to the range "
                 "edge or VWAP, and enters on the Continuation candle. It never "
                 "holds overnight because index gaps make stops unreliable. Times "
                 "are UTC for US summer time (EDT), so shift by an hour in winter.")
    open_utc = 13.5
    or_end = 14.0
    sessions = [Session("NY", 14.0, 17.0)]
    flatten_at = 19.75
    risk = RiskConfig(risk_pct=0.01, max_signals_per_session=1, max_losses_per_day=1)
    spread = 1.5

    def prepare(self, df):
        df["atr"] = atr(df, 14)
        df["vwap"] = session_vwap(df, self.open_utc)
        self.day = None
        return df

    def on_bar(self, i, df):
        ts = df.index[i]
        r = df.iloc[i]
        h = ts.hour + ts.minute / 60
        if ts.date() != self.day:
            self.day, self.hi, self.lo = ts.date(), None, None
            self.broke, self.pull, self.done = 0, None, False
        if self.open_utc <= h < self.or_end:
            self.hi = r.high if self.hi is None else max(self.hi, r.high)
            self.lo = r.low if self.lo is None else min(self.lo, r.low)
            return None
        if self.hi is None or self.done or self.session_of(ts) is None:
            return None

        if not self.broke:
            if r.close > self.hi:
                self.broke = 1
            elif r.close < self.lo:
                self.broke = -1
            return None
        d = self.broke
        edge = self.hi if d > 0 else self.lo
        # The pullback zone is whichever is closer to price: range edge or VWAP.
        zone = max(edge, r.vwap) if d > 0 else min(edge, r.vwap)
        opposite = self.lo if d > 0 else self.hi
        if (r.close - opposite) * d < 0:
            self.done = True  # full reversal through the range: no trade today
            return None
        touch = r.low if d > 0 else r.high
        if (touch - (zone + d * 0.2 * r.atr)) * d <= 0:
            self.pull = touch if self.pull is None else (
                min(self.pull, touch) if d > 0 else max(self.pull, touch))
        if self.pull is not None:
            prev = df.iloc[i - 1]
            if (r.close - r.open) * d > 0 and (r.close - r.vwap) * d > 0 and \
                    (r.close - (prev.high if d > 0 else prev.low)) * d > 0:
                self.done = True
                return Signal(d, self.pull - d * 0.2 * r.atr, tp1_r=1.0, tp2_r=2.5,
                              partial=0.5, reason="OR break, pullback to edge/VWAP")
        return None
