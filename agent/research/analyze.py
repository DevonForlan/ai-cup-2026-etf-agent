"""Aggregate leaderboards into robustness tables (no single-number winner).

  python agent\\research\\analyze.py --inputs reports\\leaderboard_main.csv [more.csv ...]

Writes:
  reports/strategy_leaderboard.csv   all strategy × window rows (official variant + stress variants)
  reports/strategy_summary.csv       per strategy: performance / robustness / risk / cost / compliance / stability
  reports/feature_ablation.csv       ablation subset of the summary
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent.config import ROOT  # noqa: E402

REPORTS = ROOT / "reports"
COLS = ["strategy_id", "group", "window", "variant", "start", "end", "days", "return", "mdd", "daily_vol",
        "turnover", "turnover_after_day1", "transaction_cost", "avg_holdings", "avg_cash", "active_share_min",
        "violations", "dq", "fallbacks", "validation_failures", "orders_per_day", "orders_per_day_after_day1",
        "hit_rate_5d", "rank_ic_1d", "rank_ic_5d", "random_percentile", "git_sha", "config_hash",
        "dataset_version", "avg_day_runtime_sec"]


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    off = df[df["variant"] == "official"]
    rnd = pd.read_csv(REPORTS / "random_baseline.csv") if (REPORTS / "random_baseline.csv").exists() else None
    out = []
    for sid, g in off.groupby("strategy_id"):
        r = g["return"]
        excess = None
        if rnd is not None:
            m = g.merge(rnd[["window", "p50", "ew150"]], on="window")
            excess = (m["return"] - m["p50"])
            vs_ew = (m["return"] - m["ew150"])
        out.append({
            "strategy_id": sid, "group": g["group"].iloc[0], "windows": len(g),
            "median_return": r.median(), "mean_return": r.mean(), "worst_return": r.min(), "best_return": r.max(),
            "positive_window_ratio": (r > 0).mean(),
            "median_excess_vs_random_p50": None if excess is None else excess.median(),
            "worst_excess_vs_random_p50": None if excess is None else excess.min(),
            "beat_random_p50_ratio": None if excess is None else (excess > 0).mean(),
            "median_excess_vs_ew150": None if excess is None else vs_ew.median(),
            "median_random_percentile": g["random_percentile"].median() if "random_percentile" in g else None,
            "min_random_percentile": g["random_percentile"].min() if "random_percentile" in g else None,
            "median_mdd": g["mdd"].median(), "worst_mdd": g["mdd"].max(),
            "mean_turnover": g["turnover"].mean(), "mean_turnover_after_day1": g["turnover_after_day1"].mean(),
            "mean_cost": g["transaction_cost"].mean(), "orders_per_day_after_day1": g["orders_per_day_after_day1"].mean(),
            "min_active_share": g["active_share_min"].min(),
            "violations": int(g["violations"].sum()), "dq_windows": int(g["dq"].astype(bool).sum()),
            "fallbacks": int(g["fallbacks"].sum()), "validation_failures": int(g["validation_failures"].sum()),
            "mean_rank_ic_1d": g["rank_ic_1d"].mean(), "mean_rank_ic_5d": g["rank_ic_5d"].mean(),
            "mean_hit_rate_5d": g["hit_rate_5d"].mean(),
            "return_std_across_windows": r.std(),
        })
    s = pd.DataFrame(out)
    ok = (s["violations"] == 0) & (s["validation_failures"] == 0) & (s["dq_windows"] == 0)
    # robustness composite: mean of ranks (lower = better); NOT a fitted objective
    comp = pd.concat([
        s["median_excess_vs_random_p50"].rank(ascending=False),
        s["worst_excess_vs_random_p50"].rank(ascending=False),
        s["beat_random_p50_ratio"].rank(ascending=False),
        s["mean_cost"].rank(ascending=True),
        s["median_mdd"].rank(ascending=True),
    ], axis=1).mean(axis=1)
    s["robust_rank_score"] = comp.where(ok)
    s["compliance_ok"] = ok
    return s.sort_values("robust_rank_score")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", required=True)
    a = ap.parse_args(argv)
    df = pd.concat([pd.read_csv(p) for p in a.inputs], ignore_index=True)
    if "error" in df:
        bad = df[df["error"].notna()]
        if len(bad):
            print("rows with errors:", len(bad))
        df = df[df["error"].isna()] if "error" in df else df
    df = df.drop_duplicates(subset=["strategy_id", "window", "variant"], keep="last")
    cols = [c for c in COLS if c in df.columns]
    df[cols].sort_values(["strategy_id", "window", "variant"]).to_csv(REPORTS / "strategy_leaderboard.csv",
                                                                       index=False, encoding="utf-8-sig")
    s = summarize(df)
    s.to_csv(REPORTS / "strategy_summary.csv", index=False, encoding="utf-8-sig")
    s[s["group"] == "ablation"].to_csv(REPORTS / "feature_ablation.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    print(s[["strategy_id", "group", "median_return", "worst_return", "positive_window_ratio",
             "median_excess_vs_random_p50", "beat_random_p50_ratio", "median_mdd", "mean_turnover", "mean_cost",
             "orders_per_day_after_day1", "violations", "fallbacks", "robust_rank_score"]].round(4).to_string())


if __name__ == "__main__":
    main()
