"""Relative strength: trailing return minus the cross-sectional median of the universe."""
from __future__ import annotations

import pandas as pd

from agent.features.momentum import trailing_return


def relative_strength(close: pd.DataFrame, n: int) -> pd.Series:
    r = trailing_return(close, n)
    return r - r.median(skipna=True)
