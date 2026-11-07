"""RESEARCH ONLY (Issue #42). Analysis of events42.csv + name-level metrics + re-entry rule R."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT / "research" / "tactical_overlay", HERE):
    sys.path.insert(0, str(p))
import lab as L  # noqa: E402
import study42 as T  # noqa: E402

R = HERE / "results"
d = pd.read_csv(R / "events42.csv")
d["ex"] = d.ret - d.base
d["rank_gain"] = d["rank"] - d["base_rank"]
rows = []


def stat(g):
    e = g.ex.dropna().to_numpy()
    if len(e) == 0:
        return None
    return dict(n=len(e), mean_pp=e.mean() * 100, median_pp=np.median(e) * 100, hit_pct=(e > 0).mean() * 100,
                p=L.signflip_p(e), rank_gain_pp=g.rank_gain.mean() * 100, mdd_delta_pp=g.mdd_delta.mean() * 100 if "mdd_delta" in g else np.nan,
                worst_pp=e.min() * 100, cost_pct=g.cost.mean() * 100, feasible_pct=100 * (1 - g.infeasible.fillna(0).mean()) if "infeasible" in g else 100)


d["infeasible"] = d.get("infeasible", 0)
d.loc[d.struct.str.startswith("T6_RANDOM"), "struct"] = "T6_RANDOM"
for kind in ("EVENT", "CONTROL"):
    for (s, x, h), g in d[(d.kind == kind) & d["size"].notna()].groupby(["struct", "size", "h"]):
        # T6 placebo: average the 20 seeds per entry first
        if s == "T6_RANDOM":
            g = g.groupby(["entry", "period"], as_index=False).agg(ex=("ex", "mean"), rank_gain=("rank_gain", "mean"), mdd_delta=("mdd_delta", "mean"),
                                                                  cost=("cost", "mean"), infeasible=("infeasible", "mean"))
        for per, gg in (("ALL", g), ("DISCOVERY", g[g.period == "DISCOVERY"]), ("OOS", g[g.period == "OOS"]),
                        ("RECENT", g[g.entry >= "2026-07-01"])):
            st = stat(gg)
            if st:
                rows.append(dict(kind=kind, struct=s, size=x, h=h, sample=per, **st))
o = pd.DataFrame(rows)
o.to_csv(R / "summary42.csv", index=False)

# benchmarks: raw return and vs frozen
b = d[d["size"].isna()].copy()
bs = b.groupby(["kind", "struct", "h", "period"]).agg(n=("ex", "size"), bench_ret_pp=("ret", lambda x: x.mean() * 100), frozen_pp=("base", lambda x: x.mean() * 100)).reset_index()
bs.to_csv(R / "benchmarks42.csv", index=False)

ev = o[o.kind == "EVENT"]
pd.set_option("display.width", 250)
print("EVENT entries:", d[d.kind == "EVENT"].entry.nunique(), "OOS:", d[(d.kind == "EVENT") & (d.period == "OOS")].entry.nunique(),
      "RECENT:", d[(d.kind == "EVENT") & (d.entry >= "2026-07-01")].entry.nunique())
prim = ev[(ev.struct == "T3_2412+BASKET") & (ev["size"].isin([0.2, 0.3, 0.4])) & (ev.h.isin([5, 10])) & (ev["sample"] == "OOS")].copy()
prim = prim.sort_values("p")
m = len(prim)
prim["p_holm"] = [min(1, (m - i) * p) for i, p in enumerate(prim.p)]
prim.to_csv(R / "primary42.csv", index=False)
print(prim.round(3).to_string(index=False))
for per in ("DISCOVERY", "OOS", "RECENT"):
    print("\n=== EVENT", per, " mean excess pp (n, hit%) by struct x size, h=5/10/24 ===")
    t = ev[(ev["sample"] == per) & (ev.h.isin([3, 5, 10, 24]))]
    pv = t.pivot_table(index=["struct", "size"], columns="h", values="mean_pp").round(2)
    print(pv.to_string())
print("\n=== EVENT OOS hit% / p (h=10) ===")
print(ev[(ev["sample"] == "OOS") & (ev.h == 10)][["struct", "size", "n", "mean_pp", "hit_pct", "p", "rank_gain_pp", "mdd_delta_pp", "worst_pp", "cost_pct", "feasible_pct"]].round(3).to_string(index=False))
print("\n=== CONTROL (all days) ALL h=10 ===")
print(o[(o.kind == "CONTROL") & (o["sample"] == "ALL") & (o.h == 10)][["struct", "size", "n", "mean_pp", "hit_pct", "p", "feasible_pct"]].round(3).to_string(index=False))
print("\n=== benchmarks EVENT OOS ===")
print(bs[(bs.kind == "EVENT") & (bs.period == "OOS")].round(2).to_string(index=False))

# leave-one-episode-out for the primary (T3, x=0.3, h=10, OOS)
g = d[(d.kind == "EVENT") & (d.struct == "T3_2412+BASKET") & (d["size"] == 0.3) & (d.h == 10) & (d.period == "OOS")].dropna(subset=["ex"])
if len(g):
    loo = [g.drop(index=i).ex.mean() * 100 for i in g.index]
    print("\nLOO T3 x=0.3 h=10 OOS: min/max of mean_pp", round(min(loo), 2), round(max(loo), 2), "n", len(g))
    print(g[["entry", "ex"]].assign(ex_pp=lambda x: x.ex * 100).round(2).to_string(index=False))

# ---- name-level metrics for 2412 vs TECH proxy / market (full sample, discovery+OOS)
data = L.Data()
tr, amt = T.build(data)
c, rt = data.close, data.ret
ew = rt.median(axis=1)
tech_ret = rt[[t for t in T.TECH if t in rt.columns]].mean(axis=1)
semi_ret = rt[[t for t in T.SEMI if t in rt.columns]].mean(axis=1)
nm = {}
nonT = [t for t in rt.columns if t not in T.TECH]
for t, r in (("2412", rt["2412"]), ("NONTECH_EW", rt[nonT].mean(axis=1)), ("FIN_EW", rt[[x for x in T.FIN if x in rt.columns]].mean(axis=1)), ("TECH_EW", tech_ret)):
    down = tech_ret < -0.015
    up = tech_ret > 0.015
    nm[t] = dict(ann_vol=r.std() * np.sqrt(245) * 100, beta_vs_tech=np.cov(r.dropna(), tech_ret.loc[r.dropna().index])[0, 1] / tech_ret.var(),
                 corr_tech=r.corr(tech_ret), corr_semi=r.corr(semi_ret), down_capture_vs_tech=r[down].mean() / tech_ret[down].mean() * 100,
                 up_capture_vs_tech=r[up].mean() / tech_ret[up].mean() * 100, mean_ret_on_tech_down_days_pct=r[down].mean() * 100,
                 mean_ret_on_tech_up_days_pct=r[up].mean() * 100, mean_ret_on_broad_selloff_days_pct=r[ew <= -0.02].mean() * 100,
                 worst_day_pct=r.min() * 100, mdd_pct=((1 + r.fillna(0)).cumprod() / (1 + r.fillna(0)).cumprod().cummax() - 1).min() * 100)
for horizon in (1, 5, 10, 20, 60):
    rs = (c / c.shift(horizon) - 1)
    nm["2412"][f"rel_{horizon}d_vs_ewuniv_latest_pct"] = float((rs["2412"] - rs.median(axis=1)).iloc[-1] * 100)
nm["2412"]["adv20_twd_m"] = float(amt.iloc[-20:].mean()["2412"] / 1e6)
nm["2412"]["div_ex_dates_2024_26"] = int(sum(1 for (dd, t) in data.div if t == "2412"))
nmd = pd.DataFrame(nm).T.round(2)
nmd.to_csv(R / "name42.csv")
print("\n=== name-level (2024-03..2026-11) ===")
print(nmd.T.to_string())
tr_events = [e for e in d[d.kind == "EVENT"].entry.unique()]
print("2412 mean fwd return after broad selloff entries (h=3,5,10) vs EW tech:")
for h in (3, 5, 10):
    a, bb = [], []
    for e in tr_events:
        i = list(c.index).index(e)
        if i + h < len(c):
            a.append(T.fwd(data, tr, i, h, {"2412": 1.0})); bb.append(T.fwd(data, tr, i, h, {t: 1 / len(T.TECH) for t in T.TECH if t in c.columns}))
    print(h, "n", len(a), "2412 %.2f%%  TECH %.2f%%  diff %.2f pp" % (np.mean(a) * 100, np.mean(bb) * 100, (np.mean(a) - np.mean(bb)) * 100))
