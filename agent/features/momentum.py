"""Price momentum features from a close-price panel (index=date asc, columns=ticker)."""
from __future__ import annotations

import pandas as pd


def trailing_return(close: pd.DataFrame, n: int) -> pd.Series:
    """close[-1] / close[-1-n] - 1 ; NaN if fewer than n+1 observations."""
    if len(close) < n + 1:
        return pd.Series(float("nan"), index=close.columns)
    last, base = close.iloc[-1], close.iloc[-1 - n]
    return last / base - 1


def distance_to_high(close: pd.DataFrame, window: int = 250, min_obs: int = 120) -> pd.Series:
    """close / max(close over window) - 1  (<= 0). NaN if history shorter than min_obs."""
    tail = close.tail(window)
    out = tail.iloc[-1] / tail.max() - 1
    counts = tail.notna().sum()
    return out.where(counts >= min_obs)
