"""RESEARCH ONLY (Issue #43). Analysis of events43.csv per PRE_REGISTRATION.md."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/"research"/"tactical_overlay"))
import lab as L
R = HERE/"results"
d = pd.read_csv(R/"events43.csv")
if "infeasible" not in d: d["infeasible"] = 0
d["infeasible"] = d.infeasible.fillna(0)
d["ex"] = d.ret - d.base
d["rank_gain"] = d["rank"] - d.base_rank
d["grp"] = np.where(d.struct.str.startswith("S6_RANDOM"), "S6_RANDOM", d.struct)
rng = np.random.default_rng(431)
def boot_ci(e):
    if len(e) < 3: return (np.nan, np.nan)
    m = [rng.choice(e, size=len(e)).mean() for _ in range(3000)]
    return (np.percentile(m, 2.5)*100, np.percentile(m, 97.5)*100)
def agg(g):   # average random seeds per entry first
    if g.grp.iloc[0] == "S6_RANDOM":
        g = g.groupby(["entry","period"], as_index=False).agg(ex=("ex","mean"), cost=("cost","mean"), rank_gain=("rank_gain","mean"), infeasible=("infeasible","mean"), ret=("ret","mean"), base=("base","mean"))
    return g
rows = []
for (s, kind, grp, x, h), g in d[d["size"].notna()].groupby(["set","grp","grp","size","h"] if False else ["set","grp","size","h"]) if False else []:
    pass
for (kind, grp, x, h), g in d.groupby(["set","grp","size","h"]):
    g = agg(g)
    for per, gg in (("ALL", g), ("DISCOVERY", g[g.period=="DISCOVERY"]), ("OOS", g[g.period=="OOS"]), ("RECENT", g[g.entry >= "2026-07-01"])):
        e = gg.ex.dropna().to_numpy()
        if len(e) == 0: continue
        lo, hi = boot_ci(e)
        rows.append(dict(set=kind, struct=grp, size=x, h=h, sample=per, n=len(e), mean_pp=e.mean()*100, median_pp=np.median(e)*100, hit_pct=(e>0).mean()*100,
                         p=L.signflip_p(e), ci_lo=lo, ci_hi=hi, rank_gain_pp=np.nanmean(gg.rank_gain)*100, worst_pp=e.min()*100,
                         cost_pct=np.nanmean(gg.cost)*100, feasible_pct=100*(1-gg.infeasible.mean())))
o = pd.DataFrame(rows); o.to_csv(R/"summary43.csv", index=False)
pd.set_option("display.width", 250)
ev = o[o.set=="E1"]
prim = ev[(ev.struct=="S1_RS5") & (ev["sample"]=="OOS")].copy().sort_values("p")
m = len(prim); prim["p_holm"] = [min(1, (m-i)*p) for i, p in enumerate(prim.p)]
prim.to_csv(R/"primary43.csv", index=False)
print("E1 events:", d[d.set=="E1"].entry.nunique(), " OOS:", d[(d.set=="E1")&(d.period=="OOS")].entry.nunique(), " RECENT:", d[(d.set=="E1")&(d.entry>="2026-07-01")].entry.nunique())
print("\nPRIMARY S1_RS5, E1, OOS (Holm over 8)"); print(prim[["size","h","n","mean_pp","median_pp","hit_pct","p","p_holm","ci_lo","ci_hi","rank_gain_pp","cost_pct","feasible_pct"]].round(3).to_string(index=False))
for per in ("DISCOVERY","OOS","RECENT"):
    print(f"\n== E1 {per}: mean excess pp, struct x size, h=1|2 ==")
    t = ev[ev["sample"]==per].pivot_table(index=["struct","size"], columns="h", values="mean_pp").round(2); print(t.to_string())
print("\n== E1 OOS hit% (h=1|2) =="); print(ev[ev["sample"]=="OOS"].pivot_table(index=["struct","size"], columns="h", values="hit_pct").round(0).to_string())
print("\n== S1_RS5 x=0.3 robustness across event definitions (mean pp, n) ==")
r = o[(o.struct=="S1_RS5") & (o["size"]==0.3) & (o["sample"].isin(["ALL","OOS"]))]
print(r.pivot_table(index=["set","sample"], columns="h", values=["mean_pp","n","p"]).round(3).to_string())
g = d[(d.set=="E1")&(d.struct=="S1_RS5")&(d["size"]==0.3)&(d.period=="OOS")].dropna(subset=["ex"])
for h in (1,2):
    gh = g[g.h==h].reset_index(drop=True)
    if len(gh)>2:
        loo = [gh.drop(index=i).ex.mean()*100 for i in range(len(gh))]
        print(f"LOO S1_RS5 x=0.3 h={h}: mean_pp range {min(loo):.2f} .. {max(loo):.2f} (n={len(gh)})")
base = d[(d.set=="E1")&(d.struct=="S1_RS5")&(d["size"]==0.3)].drop_duplicates(["entry","h"])
print("\nfrozen book mean return after E1 entries (pp): ", base.groupby(["period","h"]).base.mean().mul(100).round(2).to_dict())
print("\n== CONTROL (every 4th day) S1_RS5 mean pp (ALL) =="); print(o[(o.set=="CONTROL")&(o.struct.isin(["S1_RS5","S7_CASH","S5_EWNT","S6_RANDOM"]))&(o["sample"]=="ALL")].pivot_table(index=["struct","size"], columns="h", values="mean_pp").round(3).to_string())
