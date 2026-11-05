import sys; from pathlib import Path
import numpy as np, pandas as pd
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]
for p in (ROOT/"research"/"tactical_overlay",): sys.path.insert(0,str(p))
import lab as L
d=pd.read_csv(HERE/"results/windows41.csv"); d["src"]=d.src.replace({"DENSE24":"A"})
INIT=1e9
pl=d[d.variant=="P_RANDOM_CAP"].groupby(["src","start","period"],as_index=False).agg(ret=("ret","mean"),mdd=("mdd","mean"),turnover=("turnover","mean"),cost=("cost","mean"),viol=("viol","sum")); pl["variant"]="P_RANDOM_CAP"
d=pd.concat([d[d.variant!="P_RANDOM_CAP"],pl],ignore_index=True)
rows=[]
for src in "AB":
    g=d[d.src==src]; base=g[g.variant=="BASE"].set_index("start")
    for v in [x for x in g.variant.unique() if x!="BASE"]:
        x=g[g.variant==v].set_index("start"); ex=x.ret-base.ret.loc[x.index]
        for per,sel in (("ALL",x.index),("DISCOVERY",x.index[x.period=="DISCOVERY"]),("OOS",x.index[x.period=="OOS"]),("OOS_last6",x.index[x.period=="OOS"][-6:])):
            e=ex.loc[sel]
            rows.append(dict(src=src,variant=v,sample=per,n=len(e),ex_mean_pp=e.mean()*100,ex_median_pp=e.median()*100,better_pct=(e>1e-9).mean()*100,
              p_signflip=L.signflip_p(e.to_numpy()) if len(e) else np.nan,mdd_add_pp=(x.mdd.loc[sel]-base.mdd.loc[sel]).mean()*100,
              worst_pp=x.ret.loc[sel].min()*100,base_worst_pp=base.ret.loc[sel].min()*100,cost_add_pct=(x.cost.loc[sel]-base.cost.loc[sel]).mean()/INIT*100,
              turnover_add=(x.turnover.loc[sel]-base.turnover.loc[sel]).mean(),viol_windows=int((x.viol.loc[sel]>0).sum()),nonzero_pct=(ex.loc[sel].abs()>1e-9).mean()*100))
o=pd.DataFrame(rows); o.to_csv(HERE/"results/robust41.csv",index=False)
oo=o[o["sample"]=="OOS"]
print(oo.round(3).drop(columns=["sample"]).to_string(index=False))
print(o[o["sample"]=="OOS_last6"][["src","variant","ex_mean_pp","better_pct"]].round(3).to_string(index=False))
# half-year
b=d[d.variant=="BASE"].set_index(["src","start"])
hy=[]
for v in d.variant.unique():
    if v=="BASE":continue
    x=d[d.variant==v].set_index(["src","start"]); e=(x.ret-b.ret.loc[x.index]).rename("ex").reset_index(); e["half"]=e.start.str[:4]+"H"+np.where(e.start.str[5:7].astype(int)<=6,"1","2")
    for h,gg in e.groupby("half"): hy.append(dict(variant=v,half=h,n=len(gg),ex_mean_pp=gg["ex"].mean()*100))
pd.DataFrame(hy).to_csv(HERE/"results/halfyear41.csv",index=False)
