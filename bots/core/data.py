"""Price data: load real bars from CSV, or generate synthetic bars for testing.

Synthetic data is for checking that the plumbing works. It has no real edge
in it, so backtest numbers on it say nothing about live performance.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

_ALIASES = {
    "time": "time", "date": "time", "datetime": "time", "timestamp": "time",
    "open": "open", "o": "open", "high": "high", "h": "high",
    "low": "low", "l": "low", "close": "close", "c": "close",
    "volume": "volume", "vol": "volume", "tick_volume": "volume", "tickvol": "volume",
}


def load_csv(path: str, timeframe: str = "15min") -> pd.DataFrame:
    """Load OHLC(V) bars from TradingView / MT5 / exchange-style CSV exports.

    Timestamps are treated as UTC. Bars are resampled to `timeframe`.
    """
    raw = pd.read_csv(path, sep=None, engine="python")
    cols = {}
    for col in raw.columns:
        key = str(col).strip().strip("<>").lower()
        if key in _ALIASES and _ALIASES[key] not in cols.values():
            cols[col] = _ALIASES[key]
    raw = raw.rename(columns=cols)
    missing = {"time", "open", "high", "low", "close"} - set(raw.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    t = raw["time"]
    if pd.api.types.is_numeric_dtype(t):
        unit = "ms" if t.iloc[0] > 1e11 else "s"
        idx = pd.to_datetime(t, unit=unit, utc=True)
    else:
        idx = pd.to_datetime(t, utc=True)
    df = raw.set_index(idx)[["open", "high", "low", "close"]].astype(float)
    df["volume"] = raw["volume"].astype(float).to_numpy() if "volume" in raw else 1.0
    df = df.sort_index()
    df = df[~df.index.duplicated()]
    return df.resample(timeframe).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()


@dataclass
class Profile:
    price: float
    daily_vol: float        # typical daily % move
    weekends: bool          # trades Sat/Sun
    session_vol: dict       # UTC hour range -> volatility multiplier


PROFILES = {
    "XAUUSD": Profile(2400, 0.012, False, {(7, 11): 1.6, (12, 17): 2.0}),
    "EURUSD": Profile(1.08, 0.005, False, {(7, 11): 1.7, (12, 16): 1.5}),
    "GBPJPY": Profile(190, 0.008, False, {(0, 6): 0.5, (7, 11): 2.0, (12, 16): 1.5}),
    "BTCUSD": Profile(60000, 0.03, True, {(13, 21): 1.4}),
    "NAS100": Profile(19000, 0.013, False, {(0, 13): 0.3, (13, 20): 2.5}),
}


def synthetic(symbol: str, days: int = 250, seed: int = 7, timeframe: str = "15min") -> pd.DataFrame:
    """Regime-switching random walk shaped like the asset (vol, sessions, weekends)."""
    p = PROFILES[symbol]
    rng = np.random.default_rng(seed)
    minutes = pd.date_range("2024-01-01", periods=days * 1440, freq="1min", tz="UTC")
    if not p.weekends:
        minutes = minutes[minutes.weekday < 5]
    n = len(minutes)
    hours = minutes.hour.to_numpy()
    mult = np.ones(n)
    for (a, b), m in p.session_vol.items():
        mult[(hours >= a) & (hours < b)] = m
    mult /= np.sqrt((mult ** 2).mean())
    sigma = p.daily_vol / np.sqrt(1440) * mult

    # Trend regimes give the strategies something structured to react to.
    drift = np.zeros(n)
    pos = 0
    while pos < n:
        length = int(rng.integers(600, 4000))
        drift[pos:pos + length] = rng.normal(0, 0.015) * sigma[pos:pos + length]
        pos += length
    rets = drift + sigma * rng.standard_normal(n)
    close = p.price * np.exp(np.cumsum(rets))
    vol = rng.gamma(2.0, 50.0, n) * mult

    m = pd.DataFrame({"close": close, "volume": vol}, index=minutes)
    m["open"] = m["close"].shift(1).fillna(p.price)
    m["high"] = m[["open", "close"]].max(axis=1)
    m["low"] = m[["open", "close"]].min(axis=1)
    return m.resample(timeframe).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
