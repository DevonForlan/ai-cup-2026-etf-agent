"""Volatility features."""
from __future__ import annotations

import math

import pandas as pd


def realized_vol(close: pd.DataFrame, n: int = 20, annualize: int = 252) -> pd.Series:
    rets = close.pct_change(fill_method=None).tail(n)
    if len(close) < n + 1:
        return pd.Series(float("nan"), index=close.columns)
    return rets.std() * math.sqrt(annualize)
