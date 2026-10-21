"""RESEARCH ONLY. Paired overlay-vs-v1 statistics and the pre-registered gate (ACCEPTANCE_GATE.md §6–§7).
Inputs: results/overlay_main.csv (+ overlay_stress.csv, overlay_placebo.csv when present), window_types.csv.
Outputs: results/overlay_paired.csv, overlay_gate.csv, overlay_gate.json
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
RNG = np.random.default_rng(7)
METRICS = ["ret", "mdd", "worst_1d", "worst_5d", "cvar95_1d", "downside_vol", "sortino", "recovery_days",
           "post_day1_turnover", "cost", "max_cash", "avg_cash", "active_share_min", "violations",
           "validation_failures", "fallbacks"]


def boot_ci(x, n=10000):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 3:
        return (np.nan, np.nan)
    m = RNG.choice(x, size=(n, len(x)), replace=True).mean(axis=1)
    return float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))


def fill_identical(df: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    """Windows where the overlay never switched on are exactly BASE (not re-simulated)."""
    b = base.set_index(["wid", "cost_mult", "slippage"])
    out = df.copy()
    for i, r in out[out["identical_to_base"] == True].iterrows():  # noqa: E712
        k = (r["wid"], r["cost_mult"], r["slippage"])
        for m in METRICS:
            out.at[i, m] = b.loc[k, m]
    return out


def paired(df: pd.DataFrame, base: pd.DataFrame, wt: pd.DataFrame) -> pd.DataFrame:
    b = base.set_index(["wid", "cost_mult", "slippage"])
    typ = wt.set_index("wid")["type"]
    rows = []
    for sid, g in df.groupby("sid"):
        j = g.set_index(["wid", "cost_mult", "slippage"]).join(b[METRICS], rsuffix="_b", how="inner").reset_index()
        j["type"] = j["wid"].map(typ)
        for per in ("DISCOVERY", "VALIDATION", "HOLDOUT", "OOS", "OOS_CRASH", "OOS_BULL", "OOS_SIDEWAYS", "ALL_CRASH", "ALL"):
            if per == "ALL":
                s = j
            elif per == "OOS":
                s = j[j.period != "DISCOVERY"]
            elif per.startswith("OOS_"):
                s = j[(j.period != "DISCOVERY") & (j.type == per[4:])]
            elif per == "ALL_CRASH":
                s = j[j.type == "CRASH"]
            else:
                s = j[j.period == per]
            if not len(s):
                continue
            r = {"sid": sid, "period": per, "n": len(s), "active_windows": int((s["overlay_days"] > 0).sum()),
                 "overlay_days": int(s["overlay_days"].sum())}
            for m in ("ret", "mdd", "worst_1d", "worst_5d", "cvar95_1d", "downside_vol", "sortino"):
                d = (s[m] - s[f"{m}_b"]).astype(float)
                r[f"d_{m}"] = float(d.mean())
                r[f"{m}"], r[f"{m}_b"] = float(s[m].mean()), float(s[f"{m}_b"].mean())
            r["d_ret_median"] = float((s["ret"] - s["ret_b"]).median())
            r["ret_ci_lo"], r["ret_ci_hi"] = boot_ci(s["ret"] - s["ret_b"])
            r["mdd_ci_lo"], r["mdd_ci_hi"] = boot_ci(s["mdd"] - s["mdd_b"])
            r["mdd_max"], r["mdd_max_b"] = float(s["mdd"].max()), float(s["mdd_b"].max())
            r["worst_1d_min"], r["worst_1d_min_b"] = float(s["worst_1d"].min()), float(s["worst_1d_b"].min())
            r["worst_5d_min"], r["worst_5d_min_b"] = float(s["worst_5d"].min()), float(s["worst_5d_b"].min())
            r["recovery_mean"], r["recovery_mean_b"] = float(s["recovery_days"].mean()), float(s["recovery_days_b"].mean())
            r["post1_turn"], r["post1_turn_b"] = float(s["post_day1_turnover"].mean()), float(s["post_day1_turnover_b"].mean())
            r["cost"], r["cost_b"] = float(s["cost"].mean()), float(s["cost_b"].mean())
            r["max_cash"], r["avg_cash"], r["avg_cash_b"] = float(s["max_cash"].max()), float(s["avg_cash"].mean()), float(s["avg_cash_b"].mean())
            r["as_min"] = float(pd.to_numeric(s["active_share_min"], errors="coerce").min())
            r["viol"], r["vfail"], r["fallback"] = int(s["violations"].sum()), int(s["validation_failures"].sum()), int(s["fallbacks"].sum())
            rows.append(r)
    return pd.DataFrame(rows)


def main() -> int:
    wt = pd.read_csv(RES / "window_types.csv")
    main_ = pd.read_csv(RES / "overlay_main.csv")
    base = main_[main_.sid == "BASE_V1"].copy()
    cands = fill_identical(main_[main_.sid != "BASE_V1"], base)
    pr = paired(cands, base, wt)
    stress = None
    if (RES / "overlay_stress.csv").exists():
        st = pd.read_csv(RES / "overlay_stress.csv")
        sb = st[st.sid == "BASE_V1"]
        parts = []
        for (cm, sl), q in st.groupby(["cost_mult", "slippage"]):
            qb = q[q.sid == "BASE_V1"]
            x = paired(fill_identical(q[q.sid != "BASE_V1"], qb), qb, wt)
            x["cost_setting"] = f"cost x{cm}" if cm != 1.0 else f"slippage +{sl * 1e4:.0f}bp"
            parts.append(x)
        stress = pd.concat(parts, ignore_index=True)
        stress.to_csv(RES / "overlay_stress_paired.csv", index=False)
    pr.to_csv(RES / "overlay_paired.csv", index=False)
    P = lambda sid, per: pr[(pr.sid == sid) & (pr.period == per)].iloc[0] if len(pr[(pr.sid == sid) & (pr.period == per)]) else None  # noqa: E731
    # primary candidate: DISCOVERY only
    disc = pr[pr.period == "DISCOVERY"].copy()
    elig = disc[disc.d_ret >= -0.005].sort_values("d_mdd")
    primary = elig.sid.iloc[0] if len(elig) and elig.d_mdd.iloc[0] < 0 else None
    pl = pd.read_csv(RES / "overlay_placebo.csv") if (RES / "overlay_placebo.csv").exists() else None
    gates = []
    n_crash = int(((wt.period != "DISCOVERY") & (wt.type == "CRASH")).sum())
    for sid in sorted(pr.sid.unique()):
        o, c, bu = P(sid, "OOS"), P(sid, "OOS_CRASH"), P(sid, "OOS_BULL")
        g = {"sid": sid, "primary": sid == primary, "oos_d_ret": o.d_ret, "oos_ret_ci": [o.ret_ci_lo, o.ret_ci_hi],
             "oos_d_mdd": o.d_mdd, "oos_mdd_ci": [o.mdd_ci_lo, o.mdd_ci_hi], "oos_active_windows": int(o.active_windows)}
        g["R1_mdd"] = bool(o.d_mdd <= -0.005 and o.mdd_ci_hi < 0)
        g["R2_tail"] = bool(o.d_worst_1d >= 0 and o.d_worst_5d > 0)
        g["R3_crash"] = None if n_crash < 2 else bool(c is not None and c.d_ret >= 0 and c.d_mdd < 0)
        g["R4_bull"] = bool(bu is None or bu.d_ret >= -0.005)
        g["R5_net"] = bool(o.d_ret >= -0.003 and o.ret_ci_lo >= -0.01)
        r6 = bool(o.post1_turn <= o.post1_turn_b + 0.30 and o.cost <= o.cost_b * 1.5)
        if stress is not None:
            so = stress[(stress.sid == sid) & (stress.period == "OOS")]
            r6 = r6 and bool(len(so) and (so.d_ret >= -0.003).all())
            g["stress_d_ret"] = dict(zip(so.cost_setting, so.d_ret.round(5)))
        else:
            r6 = None
        g["R6_turnover_cost"] = r6
        g["R7_compliance"] = bool(o.viol == 0 and o.vfail == 0 and o.fallback == 0 and o.max_cash < 0.22)
        g["R8_active_share"] = bool(np.isnan(o.as_min) or o.as_min >= 0.20)
        g["R9_pit"] = True
        if pl is not None and len(pl[pl.cand == sid]):
            q = pl[pl.cand == sid].copy()
            q = fill_identical(q, base)
            pp = paired(q, base, wt)
            po = pp[pp.period == "OOS"]
            g["placebo_n"] = int(len(po))
            g["placebo_d_mdd_p05"] = float(po.d_mdd.quantile(0.05))
            g["placebo_d_mdd_mean"] = float(po.d_mdd.mean())
            g["placebo_d_worst5_median"] = float(po.d_worst_5d.median())
            g["placebo_d_ret_mean"] = float(po.d_ret.mean())
            g["placebo_rank_mdd"] = float((po.d_mdd <= o.d_mdd).mean())       # share of placebos at least as good
            g["R10_placebo"] = bool(o.d_mdd < g["placebo_d_mdd_p05"] and o.d_worst_5d > g["placebo_d_worst5_median"])
        else:
            g["R10_placebo"] = None
        keys = [k for k in g if k[:1] == "R" and k[1].isdigit()]
        g["gate_pass"] = all(g[k] is True for k in keys)
        gates.append(g)
    G = pd.DataFrame(gates)
    G.to_csv(RES / "overlay_gate.csv", index=False)
    (RES / "overlay_gate.json").write_text(json.dumps({"primary_from_discovery": primary, "oos_crash_windows": n_crash,
                                                       "gate": gates}, indent=1, default=str), encoding="utf-8")
    pd.set_option("display.width", 260)
    cols = ["sid", "period", "n", "active_windows", "d_ret", "ret_ci_lo", "ret_ci_hi", "d_mdd", "mdd_ci_hi", "d_worst_1d", "d_worst_5d", "d_cvar95_1d", "post1_turn", "post1_turn_b"]
    print(pr[pr.period.isin(["DISCOVERY", "VALIDATION", "HOLDOUT", "OOS", "OOS_CRASH", "OOS_BULL", "ALL_CRASH"])][cols].round(4).to_string())
    print("primary:", primary)
    print(G.drop(columns=[c for c in G if c.endswith("_ci")]).round(4).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
