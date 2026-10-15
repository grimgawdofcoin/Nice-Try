"""Indicators. Every one is causal: row i uses only rows <= i."""
import numpy as np
import pandas as pd


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def session_vwap(df: pd.DataFrame, start_hour: float) -> pd.Series:
    """VWAP that resets each day at start_hour (UTC). NaN before the anchor."""
    hours = df.index.hour + df.index.minute / 60
    active = hours >= start_hour
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].where(active, 0.0)
    day = df.index.normalize()
    pv = (typical * vol).groupby(day).cumsum()
    v = vol.groupby(day).cumsum()
    out = pv / v.replace(0, np.nan)
    return out.where(active)
