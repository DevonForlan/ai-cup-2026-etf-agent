"""Monthly revenue features from point-in-time revenue rows (latest month visible as_of)."""
from __future__ import annotations

import pandas as pd


def revenue_features(rev: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Returns DataFrame index=ticker, cols revenue_yoy, revenue_mom, revenue_ym (latest visible)."""
    out = pd.DataFrame(index=pd.Index(tickers, name="ticker"),
                       columns=["revenue_yoy", "revenue_mom", "revenue_ym"], dtype="object")
    if rev is None or len(rev) == 0:
        return out.astype({"revenue_yoy": "float64", "revenue_mom": "float64"})
    rev = rev.copy()
    rev["ym"] = rev["year"].astype(int) * 12 + rev["month"].astype(int) - 1
    for t, g in rev.groupby("ticker"):
        if t not in out.index:
            continue
        g = g.set_index("ym")["revenue"]
        last = g.index.max()
        cur = g.get(last)
        prev_m, prev_y = g.get(last - 1), g.get(last - 12)
        out.loc[t, "revenue_yoy"] = (cur / prev_y - 1) if prev_y and prev_y > 0 else float("nan")
        out.loc[t, "revenue_mom"] = (cur / prev_m - 1) if prev_m and prev_m > 0 else float("nan")
        out.loc[t, "revenue_ym"] = f"{last // 12:04d}-{last % 12 + 1:02d}"
    out["revenue_yoy"] = pd.to_numeric(out["revenue_yoy"], errors="coerce")
    out["revenue_mom"] = pd.to_numeric(out["revenue_mom"], errors="coerce")
    return out
