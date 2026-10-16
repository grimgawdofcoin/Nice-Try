"""Bar-by-bar backtester with the ICC risk rules baked in.

- Signals fire on a bar's close and fill at the next bar's open (no lookahead).
- If a bar touches both the stop and a target, the stop is assumed hit first.
- TP1 closes `partial` of the position and moves the stop to breakeven.
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .strategy import Signal, Strategy


@dataclass
class Trade:
    direction: int
    entry_time: pd.Timestamp
    entry: float
    stop: float
    size: float
    risk_money: float
    reason: str
    exit_time: Optional[pd.Timestamp] = None
    exit_reason: str = ""
    pnl: float = 0.0
    tp1_hit: bool = False
    initial_size: float = 0.0

    @property
    def r(self) -> float:
        return self.pnl / self.risk_money if self.risk_money else 0.0


class RiskManager:
    def __init__(self, strategy: Strategy):
        self.s = strategy
        self.cfg = strategy.risk
        self.session_signals = {}
        self.session_dirs = {}
        self.day_losses = {}

    def allows(self, ts: pd.Timestamp, direction: int) -> Optional[str]:
        """Returns the session key if the trade is allowed, else None."""
        sess = self.s.session_of(ts)
        if sess is None:
            return None
        day = ts.date()
        key = f"{day}:{sess}"
        if self.day_losses.get(day, 0) >= self.cfg.max_losses_per_day:
            return None
        if self.session_signals.get(key, 0) >= self.cfg.max_signals_per_session:
            return None
        if self.cfg.one_per_direction and direction in self.session_dirs.get(key, set()):
            return None
        return key

    def on_entry(self, key: str, direction: int):
        self.session_signals[key] = self.session_signals.get(key, 0) + 1
        self.session_dirs.setdefault(key, set()).add(direction)

    def on_exit(self, trade: Trade):
        if trade.pnl < 0:
            day = trade.entry_time.date()
            self.day_losses[day] = self.day_losses.get(day, 0) + 1


@dataclass
class Result:
    symbol: str
    trades: list
    equity: pd.Series
    start_equity: float
    open_trade: Optional[Trade] = None
    pending: Optional[Signal] = None

    def stats(self) -> dict:
        t = self.trades
        rs = np.array([x.r for x in t]) if t else np.array([])
        wins = rs[rs > 0]
        losses = rs[rs < 0]
        eq = self.equity
        dd = ((eq / eq.cummax()) - 1).min() if len(eq) else 0.0
        return {
            "symbol": self.symbol,
            "trades": len(t),
            "win_rate": float(len(wins) / len(t)) if t else 0.0,
            "avg_r": float(rs.mean()) if t else 0.0,
            "total_r": float(rs.sum()) if t else 0.0,
            "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) else float("inf") if len(wins) else 0.0,
            "max_drawdown": float(dd),
            "final_equity": float(eq.iloc[-1]) if len(eq) else self.start_equity,
            "return": float(eq.iloc[-1] / self.start_equity - 1) if len(eq) else 0.0,
        }


def backtest(strategy: Strategy, raw: pd.DataFrame, equity: float = 10_000.0,
             trade_from: Optional[pd.Timestamp] = None, close_at_end: bool = True) -> Result:
    """trade_from: ignore fills before this time (live warm-up).
    close_at_end=False leaves the last position open (live mode)."""
    df = strategy.prepare(raw.copy())
    if "atr" not in df:
        raise ValueError(f"{strategy.symbol}: prepare() must add an 'atr' column")
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = df["atr"].to_numpy()
    idx = df.index
    hours = idx.hour + idx.minute / 60
    half_spread = strategy.spread / 2

    rm = RiskManager(strategy)
    start = equity
    trades, curve = [], np.empty(len(df))
    pos: Optional[Trade] = None
    pending: Optional[Signal] = None
    tp1 = tp2 = None
    bars_in = 0
    sig: Optional[Signal] = None

    def close(trade, price, frac, ts, why):
        nonlocal equity
        qty = trade.size * frac
        pnl = (price - trade.entry) * trade.direction * qty - half_spread * qty
        trade.pnl += pnl
        equity += pnl
        trade.size -= qty
        if trade.size <= 1e-12:
            trade.exit_time, trade.exit_reason = ts, why

    for i in range(len(df)):
        ts = idx[i]

        # 1) Fill the signal from the previous bar.
        if pending is not None and pos is None:
            s, pending = pending, None
            key = rm.allows(ts, s.direction) if trade_from is None or ts >= trade_from else None
            fill = o[i] + half_spread * s.direction
            dist = (fill - s.stop) * s.direction
            if key and dist > 0:
                risk_money = equity * strategy.risk.risk_pct * s.risk_scale
                size = risk_money / dist
                if strategy.max_leverage:
                    size = min(size, equity * strategy.max_leverage / fill)
                    risk_money = size * dist
                pos = Trade(s.direction, ts, fill, s.stop, size, risk_money, s.reason)
                pos.initial_size = pos.size
                tp1 = fill + s.direction * s.tp1_r * dist
                tp2 = None
                if s.tp2_price is not None and (s.tp2_price - tp1) * s.direction > 0:
                    tp2 = s.tp2_price
                elif s.tp2_r is not None:
                    tp2 = fill + s.direction * s.tp2_r * dist
                sig, bars_in = s, 0
                rm.on_entry(key, s.direction)

        # 2) Manage the open position against this bar.
        if pos is not None:
            d = pos.direction
            bars_in += 1
            adverse = l[i] if d > 0 else h[i]
            favorable = h[i] if d > 0 else l[i]
            if (adverse - pos.stop) * d <= 0:
                px = o[i] if (o[i] - pos.stop) * d < 0 else pos.stop  # gap through stop
                close(pos, px, 1.0, ts, "breakeven" if pos.tp1_hit else "stop")
            else:
                if not pos.tp1_hit and (favorable - tp1) * d >= 0:
                    close(pos, tp1, sig.partial, ts, "tp1")
                    pos.tp1_hit = True
                    pos.stop = pos.entry
                if pos.size > 0 and tp2 is not None and (favorable - tp2) * d >= 0:
                    close(pos, tp2, 1.0, ts, "tp2")
                if pos.size > 0:
                    if sig.trail_atr and pos.tp1_hit:
                        trail = c[i] - d * sig.trail_atr * a[i]
                        if (trail - pos.stop) * d > 0:
                            pos.stop = trail
                    if strategy.flatten_at is not None and hours[i] + 0.25 >= strategy.flatten_at \
                            and hours[i] < strategy.flatten_at + 1:
                        close(pos, c[i], 1.0, ts, "session_close")
                    elif sig.max_bars and bars_in >= sig.max_bars:
                        close(pos, c[i], 1.0, ts, "time")
            if pos.exit_time is not None:
                trades.append(pos)
                rm.on_exit(pos)
                pos = None

        # 3) Ask the bot for a new signal (it sees bars up to and including i).
        s = strategy.on_bar(i, df)
        if s is not None and pos is None:
            pending = s

        curve[i] = equity

    if pos is not None and close_at_end:
        close(pos, c[-1], 1.0, idx[-1], "end_of_data")
        trades.append(pos)
        curve[-1] = equity
        pos = None

    return Result(strategy.symbol, trades, pd.Series(curve, index=idx), start,
                  open_trade=pos, pending=pending if pos is None else None)
