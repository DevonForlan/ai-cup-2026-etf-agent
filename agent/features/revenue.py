"""Monthly revenue features from point-in-time revenue rows (latest month visible as_of).
Vectorised: latest visible month per ticker, compared with month-1 (MoM) and month-12 (YoY)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def revenue_features(rev: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Returns DataFrame index=ticker, cols revenue_yoy, revenue_mom, revenue_ym (latest visible)."""
    out = pd.DataFrame(index=pd.Index(tickers, name="ticker"))
    out["revenue_yoy"] = np.nan
    out["revenue_mom"] = np.nan
    out["revenue_ym"] = None
    if rev is None or len(rev) == 0:
        return out
    r = pd.DataFrame({"ticker": rev["ticker"].astype(str).to_numpy(),
                      "ym": (rev["year"].astype(int) * 12 + rev["month"].astype(int) - 1).to_numpy(),
                      "revenue": rev["revenue"].astype(float).to_numpy()})
    r = r.dropna(subset=["revenue"])
    val = dict(zip(zip(r["ticker"], r["ym"]), r["revenue"]))
    last = r.groupby("ticker")["ym"].max()
    for t, ym in last.items():
        if t not in out.index:
            continue
        cur = val.get((t, ym))
        pm, py = val.get((t, ym - 1)), val.get((t, ym - 12))
        out.at[t, "revenue_yoy"] = cur / py - 1 if py and py > 0 else np.nan
        out.at[t, "revenue_mom"] = cur / pm - 1 if pm and pm > 0 else np.nan
        out.at[t, "revenue_ym"] = f"{ym // 12:04d}-{ym % 12 + 1:02d}"
    return out
