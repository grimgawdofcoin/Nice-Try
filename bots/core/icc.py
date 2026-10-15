"""Indication -> Correction -> Continuation detector.

The tracker only understands longs. Shorts are found by feeding it the mirrored
price series (every price negated), so both sides share the same logic.
"""
from collections import deque
from dataclasses import dataclass


@dataclass
class ICCParams:
    lookback: int = 20          # bars defining the structure that must break
    impulse_atr: float = 2.0    # minimum indication leg, in ATR
    zone: tuple = (0.382, 0.618)  # retracement band that counts as the AOI
    invalid: float = 0.786      # deeper than this = correction became reversal
    max_corr_bars: int = 24     # correction taking longer than this is stale
    sweep_lookback: int = 6     # bars used to judge a liquidity sweep


@dataclass
class ICCEvent:
    direction: int      # +1 long, -1 short
    origin: float       # start of the indication leg
    extreme: float      # end of the indication leg
    corr_extreme: float  # deepest point of the correction (stop anchor)
    swept: bool         # correction ran stops then reclaimed
    retrace: float      # deepest retracement reached (0..1)


class _LongTracker:
    def __init__(self, p: ICCParams):
        self.p = p
        self.bars = deque(maxlen=max(p.lookback, p.sweep_lookback) + 1)
        self._reset()

    def _reset(self):
        self.active = False
        self.origin = self.extreme = self.corr_low = None
        self.in_zone = self.swept = False
        self.bars_since_extreme = 0
        self.max_retrace = 0.0

    def update(self, o, h, l, c, a):
        hist = list(self.bars)
        self.bars.append((o, h, l, c))
        if len(hist) < self.p.lookback or not a or a != a:
            return None
        prev = hist[-1]
        window = hist[-self.p.lookback:]

        if self.active:
            leg = self.extreme - self.origin
            if h > self.extreme and not self.in_zone:
                # Indication still extending, no pullback yet.
                self.extreme = h
                self.bars_since_extreme = 0
                return None
            self.bars_since_extreme += 1
            retrace = (self.extreme - l) / leg if leg > 0 else 0
            self.max_retrace = max(self.max_retrace, retrace)
            if l <= self.origin or self.max_retrace > self.p.invalid or \
                    self.bars_since_extreme > self.p.max_corr_bars:
                self._reset()
            else:
                if self.max_retrace >= self.p.zone[0]:
                    self.in_zone = True
                self.corr_low = l if self.corr_low is None else min(self.corr_low, l)
                recent_low = min(b[2] for b in hist[-self.p.sweep_lookback:])
                if l < recent_low and c > recent_low:
                    self.swept = True
                confirm = c > o and c > prev[1]
                if self.in_zone and confirm:
                    ev = ICCEvent(1, self.origin, self.extreme, self.corr_low,
                                  self.swept, self.max_retrace)
                    self._reset()
                    return ev
                return None

        # Look for a fresh indication: close breaks structure with a real leg.
        struct_high = max(b[1] for b in window)
        origin = min(min(b[2] for b in window), l)
        if c > struct_high and (h - origin) >= self.p.impulse_atr * a:
            self._reset()
            self.active = True
            self.origin, self.extreme = origin, h
        return None


class ICCDetector:
    """Feeds each bar to a long tracker and a mirrored short tracker."""

    def __init__(self, params: ICCParams):
        self.long = _LongTracker(params)
        self.short = _LongTracker(params)

    def update(self, o, h, l, c, a):
        events = []
        ev = self.long.update(o, h, l, c, a)
        if ev:
            events.append(ev)
        ev = self.short.update(-o, -l, -h, -c, a)
        if ev:
            events.append(ICCEvent(-1, -ev.origin, -ev.extreme, -ev.corr_extreme,
                                   ev.swept, ev.retrace))
        return events
