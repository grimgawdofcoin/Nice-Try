from ..core.indicators import atr
from ..core.strategy import RiskConfig, Session, Signal, Strategy


class DragonRetest(Strategy):
    symbol = "GBPJPY"
    name = "Dragon Asian-Range Retest"
    style = "London break of the Asian range, entry on the retest"
    rationale = ("GBPJPY sits in a tight range during Tokyo, then London volume "
                 "breaks it hard. Chasing that break gives bad fills on a pair this "
                 "volatile, so this bot treats the break as the Indication, the "
                 "retest of the range edge as the Correction, and buys or sells "
                 "the Continuation candle. Target is the range height projected "
                 "from the edge.")
    sessions = [Session("London", 7, 11)]
    risk = RiskConfig(risk_pct=0.0075, max_signals_per_session=1, max_losses_per_day=1)
    spread = 0.03
    asian = (0, 6)
    min_range_atr, max_range_atr = 2.0, 10.0

    def prepare(self, df):
        df["atr"] = atr(df, 14)
        self.day = None
        return df

    def _new_day(self, day):
        self.day = day
        self.hi = self.lo = None
        self.broke = 0       # +1 broke up, -1 broke down
        self.retested = False
        self.pull_extreme = None
        self.done = False

    def on_bar(self, i, df):
        ts = df.index[i]
        r = df.iloc[i]
        if ts.date() != self.day:
            self._new_day(ts.date())
        h = ts.hour + ts.minute / 60

        if self.asian[0] <= h < self.asian[1]:
            self.hi = r.high if self.hi is None else max(self.hi, r.high)
            self.lo = r.low if self.lo is None else min(self.lo, r.low)
            return None
        if self.hi is None or self.done or self.session_of(ts) is None:
            return None
        height = self.hi - self.lo
        if not (self.min_range_atr * r.atr <= height <= self.max_range_atr * r.atr):
            return None
        mid = (self.hi + self.lo) / 2

        if not self.broke:
            if r.close > self.hi + 0.1 * r.atr:
                self.broke = 1
            elif r.close < self.lo - 0.1 * r.atr:
                self.broke = -1
            return None

        d = self.broke
        edge = self.hi if d > 0 else self.lo
        # Back inside past the midpoint = failed break, stand down for the day.
        if (r.close - mid) * d < 0:
            self.done = True
            return None
        touch = r.low if d > 0 else r.high
        if (touch - (edge + d * 0.25 * r.atr)) * d <= 0:
            self.retested = True
            self.pull_extreme = touch if self.pull_extreme is None else (
                min(self.pull_extreme, touch) if d > 0 else max(self.pull_extreme, touch))
        if self.retested:
            prev = df.iloc[i - 1]
            confirm = (r.close - r.open) * d > 0 and (r.close - (prev.high if d > 0 else prev.low)) * d > 0
            if confirm:
                self.done = True
                stop = self.pull_extreme - d * 0.3 * r.atr
                return Signal(d, stop, tp1_r=1.0, tp2_r=2.0, tp2_price=edge + d * height,
                              partial=0.5, max_bars=24, reason="asian range retest")
        return None
