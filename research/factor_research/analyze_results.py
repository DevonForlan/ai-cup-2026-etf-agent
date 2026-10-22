"""RESEARCH ONLY. Paired comparison of every candidate vs BASE_V1 on identical windows.
Writes results/paired_summary.csv and prints a compact table. Screening uses DISCOVERY only (ACCEPTANCE_GATE.md)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "research" / "factor_research" / "results"
RNG = np.random.default_rng(7)


def boot_ci(x: np.ndarray, n: int = 10000) -> tuple[float, float]:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 3:
        return (np.nan, np.nan)
    m = RNG.choice(x, size=(n, len(x)), replace=True).mean(axis=1)
    return float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))


def random_pct(df: pd.DataFrame) -> pd.Series:
    rb = json.loads((RES / "random_baseline.json").read_text(encoding="utf-8"))
    return df.apply(lambda r: float((np.array(rb[r["wid"]]) < r["ret"]).mean() * 100), axis=1)


def paired(df: pd.DataFrame, base_sid: str = "BASE_V1") -> pd.DataFrame:
    df = df[df["error"].isna()] if "error" in df else df
    # main statistics at OFFICIAL cost only (cost stress is evaluated separately; pooling cost variants would
    # pseudo-replicate each window)
    df = df[(df["cost_mult"] == 1.0) & (df["slippage"] == 0.0)].copy()
    df["rand_pct"] = random_pct(df)
    keys = ["wid", "cost_mult", "slippage"]
    b = df[df.sid == base_sid].set_index(keys)
    rows = []
    for sid, g in df[df.sid != base_sid].groupby("sid"):
        g = g.set_index(keys)
        j = g.join(b, rsuffix="_b", how="inner")
        for per in ("DISCOVERY", "VALIDATION", "HOLDOUT", "OOS", "ALL"):
            s = j if per == "ALL" else (j[j.period.isin(["VALIDATION", "HOLDOUT"])] if per == "OOS" else j[j.period == per])
            if not len(s):
                continue
            d = s["ret"] - s["ret_b"]
            lo, hi = boot_ci(d.to_numpy())
            rows.append({"sid": sid, "period": per, "n": len(s), "d_ret_mean": d.mean(), "d_ret_median": d.median(),
                         "win_share": float((d > 0).mean()), "ci_lo": lo, "ci_hi": hi,
                         "ret_median": s["ret"].median(), "ret_median_b": s["ret_b"].median(),
                         "worst": s["ret"].min(), "worst_b": s["ret_b"].min(),
                         "mdd_mean": s["mdd"].mean(), "mdd_mean_b": s["mdd_b"].mean(),
                         "mdd_max": s["mdd"].max(), "mdd_max_b": s["mdd_b"].max(),
                         "post1_turn": s["post_day1_turnover"].mean(), "post1_turn_b": s["post_day1_turnover_b"].mean(),
                         "cost": s["cost"].mean(), "cost_b": s["cost_b"].mean(),
                         "as_min": s["active_share_min"].min(), "viol": int(s["violations"].sum()),
                         "viol_b": int(s["violations_b"].sum()), "vfail": int(s["validation_failures"].sum()),
                         "fallback": int(s["fallbacks"].sum()), "sortino": s["sortino"].median(),
                         "sortino_b": s["sortino_b"].median(), "worst_1d": s["worst_1d"].min(),
                         "worst_1d_b": s["worst_1d_b"].min(), "cvar95": s["cvar95_1d"].mean(),
                         "cvar95_b": s["cvar95_1d_b"].mean(), "rand_pct_median": s["rand_pct"].median(),
                         "rand_pct_median_b": s["rand_pct_b"].median(),
                         "above_rand_median": int((s["rand_pct"] > 50).sum()), "above_rand_median_b": int((s["rand_pct_b"] > 50).sum())})
    return pd.DataFrame(rows)


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "portfolio_single.csv"
    df = pd.read_csv(RES / name)
    out = paired(df)
    out.to_csv(RES / name.replace(".csv", "_paired.csv"), index=False)
    pd.set_option("display.width", 260)
    piv = out.pivot(index="sid", columns="period", values="d_ret_mean")
    print((piv * 100).round(2).sort_values("DISCOVERY", ascending=False).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
