from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class Signal:
    direction: int                 # +1 long, -1 short
    stop: float                    # absolute stop price
    tp1_r: float = 1.0             # first target in R; partial + stop to breakeven
    tp2_r: Optional[float] = 2.0   # final target in R (None = ride the trail)
    tp2_price: Optional[float] = None  # structural target, used if beyond TP1
    partial: float = 0.5           # fraction closed at TP1
    trail_atr: Optional[float] = None  # chandelier trail after TP1, in ATR
    max_bars: Optional[int] = None  # time stop
    risk_scale: float = 1.0        # multiplies the bot's base risk
    reason: str = ""


@dataclass
class Session:
    name: str
    start: float  # UTC hour, e.g. 13.5 = 13:30
    end: float


@dataclass
class RiskConfig:
    risk_pct: float = 0.01
    max_signals_per_session: int = 2
    max_losses_per_day: int = 2
    one_per_direction: bool = True


class Strategy:
    """Base class. Each asset bot overrides everything that matters to it."""

    symbol = ""
    name = ""
    style = ""
    rationale = ""
    sessions: list = []             # empty = trades around the clock
    risk = RiskConfig()
    spread = 0.0                    # round-trip cost in price units
    flatten_at: Optional[float] = None  # UTC hour to close any open trade
    trade_weekends = False

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def on_bar(self, i: int, df: pd.DataFrame) -> Optional[Signal]:
        raise NotImplementedError

    def session_of(self, ts: pd.Timestamp) -> Optional[str]:
        if not self.trade_weekends and ts.weekday() >= 5:
            return None
        if not self.sessions:
            return "24h"
        h = ts.hour + ts.minute / 60
        for s in self.sessions:
            if s.start <= h < s.end:
                return s.name
        return None

    def describe(self) -> str:
        sess = ", ".join(f"{s.name} {s.start:g}-{s.end:g}h" for s in self.sessions) or "24/7"
        return (f"{self.symbol}: {self.name} ({self.style})\n"
                f"  sessions (UTC): {sess}\n"
                f"  risk/trade: {self.risk.risk_pct:.2%}, max {self.risk.max_signals_per_session}"
                f" signals/session, stop after {self.risk.max_losses_per_day} losses/day\n"
                f"  why: {self.rationale}")
