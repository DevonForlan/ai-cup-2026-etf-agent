"""Institutional flow (三大法人) features. Normalised by average daily volume so that large and
small caps are comparable; raw share sums are kept for evidence facts."""
from __future__ import annotations

import pandas as pd


def net_flow_shares(total_net: pd.DataFrame, n: int) -> pd.Series:
    if len(total_net) < n:
        return pd.Series(float("nan"), index=total_net.columns)
    return total_net.tail(n).sum(min_count=n)


def flow_intensity(total_net: pd.DataFrame, volume: pd.DataFrame, n: int, vol_window: int = 20) -> pd.Series:
    flow = net_flow_shares(total_net, n)
    adv = volume.tail(vol_window).mean() if len(volume) >= vol_window else pd.Series(float("nan"), index=volume.columns)
    return flow / (adv * n)
