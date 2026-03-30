"""
ta_compat.py — Minimal pandas_ta drop-in for Python 3.11+
==========================================================
Implements exactly the five indicators used by this project:
  ema, rsi, atr, adx, obv

All functions match the pandas_ta call signature and return type so that
trade_manager.py and scanner.py require zero changes.
"""

import numpy as np
import pandas as pd


def ema(series: pd.Series, length: int) -> pd.Series:
    """Exponential Moving Average — matches pandas_ta.ema()."""
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """Relative Strength Index — matches pandas_ta.rsi()."""
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Average True Range — matches pandas_ta.atr()."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.DataFrame:
    """
    Average Directional Index — matches pandas_ta.adx().

    Returns a DataFrame with columns:
      ADX_{length}   — trend strength (0-100)
      DMP_{length}   — +DI (positive directional indicator)
      DMN_{length}   — -DI (negative directional indicator)
    """
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)
    prev_close = close.shift(1)

    # True Range
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Directional movement
    up_move   = high - prev_high
    down_move = prev_low - low
    plus_dm   = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm  = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_s  = pd.Series(plus_dm,  index=high.index)
    minus_dm_s = pd.Series(minus_dm, index=high.index)

    # Smoothed TR and DMs
    def _smooth(s):
        return s.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()

    tr_smooth   = _smooth(tr)
    plus_di     = 100 * _smooth(plus_dm_s)  / tr_smooth.replace(0, np.nan)
    minus_di    = 100 * _smooth(minus_dm_s) / tr_smooth.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = _smooth(dx)

    return pd.DataFrame({
        f"ADX_{length}": adx_val,
        f"DMP_{length}": plus_di,
        f"DMN_{length}": minus_di,
    }, index=high.index)


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume — matches pandas_ta.obv()."""
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()