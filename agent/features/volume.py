"""Volume / liquidity features."""
from __future__ import annotations

import pandas as pd


def volume_ratio(volume: pd.DataFrame, short: int = 5, long: int = 60) -> pd.Series:
    if len(volume) < long:
        return pd.Series(float("nan"), index=volume.columns)
    return volume.tail(short).mean() / volume.tail(long).mean()


def avg_traded_value(amount: pd.DataFrame, n: int = 20) -> pd.Series:
    if len(amount) < n:
        return pd.Series(float("nan"), index=amount.columns)
    return amount.tail(n).mean()
