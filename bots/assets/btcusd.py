from ..core.indicators import atr, ema
from ..core.strategy import RiskConfig, Signal, Strategy


class TrendRider(Strategy):
    symbol = "BTCUSD"
    name = "BTC Trend Rider"
    style = "EMA-band pullbacks in a stacked trend, trailing exit"
    rationale = ("Bitcoin trades 24/7 and trends in big, wicky legs. Fixed targets "
                 "cut winners short, so this bot only trades when the EMAs are "
                 "stacked, uses the 21-50 EMA band as a moving AOI, gives the stop "
                 "a full ATR of room, and after TP1 rides the rest with a 3-ATR "
                 "trail. Risk is halved on weekends because liquidity is thin.")
    sessions = []
    trade_weekends = True
    risk = RiskConfig(risk_pct=0.0075, max_signals_per_session=2, max_losses_per_day=2)
    spread = 15.0
    break_lookback = 40
    max_wait = 30

    def prepare(self, df):
        df["atr"] = atr(df, 14)
        df["e21"] = ema(df["close"], 21)
        df["e50"] = ema(df["close"], 50)
        df["e200"] = ema(df["close"], 200)
        df["hh"] = df["high"].rolling(self.break_lookback).max().shift(1)
        df["ll"] = df["low"].rolling(self.break_lookback).min().shift(1)
        self.armed = 0
        self.armed_at = 0
        self.pull = None
        return df

    def on_bar(self, i, df):
        if i < 200:
            return None
        r, prev = df.iloc[i], df.iloc[i - 1]
        trend = 1 if r.e50 > r.e200 and r.close > r.e200 else \
            -1 if r.e50 < r.e200 and r.close < r.e200 else 0

        # Indication: break of 40-bar structure in the trend's direction.
        if trend and ((trend > 0 and r.close > r.hh) or (trend < 0 and r.close < r.ll)):
            self.armed, self.armed_at, self.pull = trend, i, None
            return None
        d = self.armed
        if not d or trend != d or i - self.armed_at > self.max_wait:
            self.armed = 0
            return None

        # Correction: price dips into the 21-50 EMA band without closing through the 50.
        band_edge = max(r.e21, r.e50) if d > 0 else min(r.e21, r.e50)
        deep_edge = r.e50 - d * 0.5 * r.atr
        touch = r.low if d > 0 else r.high
        if (touch - band_edge) * d <= 0:
            if (r.close - deep_edge) * d < 0:
                self.armed = 0
                return None
            self.pull = touch if self.pull is None else (
                min(self.pull, touch) if d > 0 else max(self.pull, touch))

        # Continuation: candle closes through the previous bar's extreme.
        if self.pull is not None and (r.close - r.open) * d > 0 and \
                (r.close - (prev.high if d > 0 else prev.low)) * d > 0:
            stop = self.pull - d * 1.0 * r.atr
            self.armed = 0
            weekend = df.index[i].weekday() >= 5
            return Signal(d, stop, tp1_r=1.5, tp2_r=None, partial=0.33, trail_atr=3.0,
                          risk_scale=0.5 if weekend else 1.0, reason="EMA band pullback")
        return None
