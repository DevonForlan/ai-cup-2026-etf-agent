"""Phase 5B — bounded signal fusion (deterministic).

  final_score = quant_score + adjustment
  adjustment  = max_percentile_adjustment / 100 × event_score,   event_score ∈ [-1, 1]

event_score comes from validated EventFacts only (confidence ≥ min_confidence, published ≤ cutoff,
known ticker, decayed over horizon_days). Only ELIGIBLE names in the 150-stock universe can be adjusted;
the LLM cannot create candidates, change caps, cash, Active Share or any risk gate. Every component is
kept in the score table for audit."""
from __future__ import annotations

import pandas as pd


def fuse(scores: pd.DataFrame, event_score: dict[str, dict], max_pct: float) -> tuple[pd.DataFrame, dict]:
    out = scores.copy()
    out["quant_score"] = out["score"]
    es = pd.Series({t: d["score"] for t, d in event_score.items()}, dtype="float64").reindex(out.index).fillna(0.0)
    elig = out["eligible"].astype(bool) & out["score"].notna()
    adj = (es * float(max_pct) / 100.0).where(elig, 0.0)
    out["event_score"] = es
    out["adjustment"] = adj
    out["score"] = (out["quant_score"] + adj).where(elig)
    out["rank"] = out["score"].rank(ascending=False, method="first")
    audit = {t: {"quant_score": float(out.at[t, "quant_score"]), "event_score": float(es[t]),
                 "adjustment": float(adj[t]), "final_score": float(out.at[t, "score"]),
                 "events": event_score[t]["events"]}
             for t in event_score if t in out.index and elig.get(t, False)}
    return out.sort_values("rank", na_position="last"), audit
