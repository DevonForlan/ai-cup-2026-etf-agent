"""Cross-sectional ranking. Each feature -> percentile rank in the eligible universe
(missing -> neutral 0.5). Score = Σ weight_f × pct_f with weights from config/strategy.yaml."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from agent.config import ROOT

# For these features a HIGHER raw value is better before applying the configured sign.
METHOD_WEIGHTS = {
    "B1_score_equal": None,             # uses score_weights
    "B0_score_tiered": None,
    "B2_momentum": {"ret_20d": 1.0},
    "B3_institutional": {"institutional_flow_5d": 1.0},
}


def eligible_mask(f: pd.DataFrame, min_obs: int = 21, min_avg_value: float = 5e7) -> pd.Series:
    ok = f["close_prev"].notna() & (f["close_prev"] > 0)
    ok &= f.get("n_obs", pd.Series(0, index=f.index)).fillna(0) >= min_obs
    if "avg_value_20d" in f:
        ok &= f["avg_value_20d"].fillna(0) >= min_avg_value
    return ok


def score(features: pd.DataFrame, weights: dict[str, float], method: str = "B0_score_tiered",
          min_obs: int = 21, min_avg_value: float = 5e7) -> pd.DataFrame:
    f = features.copy()
    elig = eligible_mask(f, min_obs, min_avg_value)
    w = METHOD_WEIGHTS.get(method) or weights
    out = pd.DataFrame(index=f.index)
    out["eligible"] = elig
    total = pd.Series(0.0, index=f.index)
    for feat, wt in w.items():
        if not wt or feat not in f:
            continue
        col = f[feat].where(elig)
        pct = col.rank(pct=True, method="average")
        out[f"pct_{feat}"] = pct
        total += wt * pct.fillna(0.5)
    out["score"] = total.where(elig)
    out["rank"] = out["score"].rank(ascending=False, method="first")
    out["method"] = method
    return out.sort_values("rank", na_position="last")


def save_scores(scores: pd.DataFrame, trade_date: str, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or ROOT / "data" / "processed" / "scores"
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{trade_date.replace('-', '')}.parquet"
    scores.reset_index().to_parquet(p, index=False)
    return p
