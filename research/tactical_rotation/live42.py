"""RESEARCH ONLY (Issue #42). Live-book (DataPack 2026-11-06 holdings) what-if: liquidity, official Active Share, costs.
Nothing is submitted or written outside research/tactical_rotation/results."""
import sys, json, csv
from decimal import Decimal
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[1]
MAIN = Path(r"C:/Users/devon.tseng/Desktop/個人/AI CUP 2026玉山人工智慧公開挑戰賽")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/"research"/"tactical_overlay"))
import lab as L
from agent.engine.active_share import compute_official_active_share
TECH_S = {"半導體業","電腦及週邊設備業","電子零組件業","其他電子業","通信網路業","光電業","電子通路業"}
SM = L.sector_map(); TECH = {t for t,s in SM.items() if s in TECH_S}
dp = json.load(open(MAIN/"data/official_datapack/DataPack_304_2026-11-06.json", encoding="utf-8"))
acc = dp["account"]; nav = acc["nav_tradable"] if acc.get("nav_tradable") else acc["aum"]
hold = {h["code"]: h for h in dp["holdings"]}
W = {t: h["shares"]*h["close_price"]/nav for t,h in hold.items()}
cash = acc["cash"]/nav
px = pd.read_parquet(MAIN/"data/history/daily_prices.parquet"); px["ticker"]=px.ticker.astype(str)
last = px.date.max()
amt = px.assign(a=px.close*px.volume).pivot_table(index="date",columns="ticker",values="a").sort_index()
adv = amt.iloc[-20:].mean(); close = px[px.date==last].set_index("ticker").close
etfs=[r["etf_code"] for r in csv.DictReader(open(MAIN/"config/active_etf_list.csv",encoding="utf-8-sig"))]
eh = pd.read_parquet(MAIN/"data/history/etf_holdings.parquet"); eh=eh[(eh.synthetic==False)]
ld = eh.date.max(); eh = eh[eh.date==ld]
bench = {e:{str(r.ticker):Decimal(str(r.weight)) for r in g.itertuples()} for e,g in eh.groupby("etf")}
def AS(w, c):
    r = compute_official_active_share({t:Decimal(str(v)) for t,v in w.items()}, bench, etfs, port_cash=Decimal(str(c)), include_cash=False)
    return r
def asval(w,c):
    return round(float(AS(w,c).minimum_active_share)*100,2)
tw = sum(v for t,v in W.items() if t in TECH)
print("nav",nav,"cash",round(cash,4),"names",len(W),"tech_w",round(tw,4),"bench date",ld,"n_etf",len(bench))
print("AS control", asval(W,cash))
nonT = [t for t in px.ticker.unique() if t not in TECH and t!="2412" and t in set(L.universe())]
top = list(adv[nonT].sort_values(ascending=False).index[:5])
print("top6 liquid non-tech:", top, [SM[t] for t in top])
rows=[]
for x in (0.10,0.20,0.30,0.40):
    for name, sl in (("T1_2412",["2412"]),("T3_2412+BASKET",["2412"]+top),("T2_BASKET",top+[list(adv[nonT].sort_values(ascending=False).index)[5]])):
        new={t:(v*(1-x/tw) if t in TECH else v) for t,v in W.items()}
        rem=x
        for _ in range(12):
            op=[t for t in sl if (0.25 if t=="2330" else 0.10)-new.get(t,0)>1e-9]
            if not op or rem<1e-9: break
            sh=rem/len(op)
            for t in op:
                a=min(sh,0.10-new.get(t,0)); new[t]=new.get(t,0)+a; rem-=a
        bought=x-rem; cost=x*(0.001425+0.003)+bought*0.001425
        newcash=cash+x-bought-cost
        part={t: (new.get(t,0)-W.get(t,0))*nav/adv[t] for t in sl if t in adv.index}
        rows.append(dict(struct=name,x_req=x,x_filled=round(bought,4),tech_after=round(sum(v for t,v in new.items() if t in TECH),4),cash_after=round(newcash,4),names=len(new),
            w2412=round(new.get("2412",0),4),cost_pct=round(cost*100,3),turnover_pct=round((x+bought)*100,1),active_share=asval(new,newcash),
            max_part_pct=round(max(part.values())*100,2) if part else None))
d=pd.DataFrame(rows); d.to_csv(HERE/"results/live_whatif42.csv",index=False); print(d.to_string(index=False))
print("2412 adv20 (TWD m):",round(adv["2412"]/1e6), "10% NAV =",round(0.10*nav/1e6),"m ->",round(0.10*nav/adv["2412"]*100,2),"% of ADV; held now:",round(W.get("2412",0),4))
for t in top: print(t,SM[t],round(adv[t]/1e6),"m ADV; 10% NAV =",round(0.10*nav/adv[t]*100,2),"%")
