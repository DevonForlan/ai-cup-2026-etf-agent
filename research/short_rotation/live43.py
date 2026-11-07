"""RESEARCH ONLY (Issue #43). As-of 2026-11-06 ranking + concrete lot-sized what-if orders for Mon 2026-11-09. Nothing is submitted."""
import sys, json, csv
from decimal import Decimal
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[1]
MAIN = Path(r"C:/Users/devon.tseng/Desktop/個人/AI CUP 2026玉山人工智慧公開挑戰賽")
sys.path.insert(0, str(HERE)); import study43 as S
from agent.engine.active_share import compute_official_active_share
T, L = S.T, S.L
FEE, TAX = S.FEE, S.TAX
data = L.Data(); tr, amt = T.build(data)
d_idx = len(data.close) - 1; asof = data.close.index[d_idx]
f = S.features(data, amt, d_idx)
dp = json.load(open(MAIN/"data/official_datapack/DataPack_304_2026-11-06.json", encoding="utf-8"))
cash0 = dp["account"]["cash"]; hold = {h["code"]: h["shares"] for h in dp["holdings"]}
close = data.close.iloc[d_idx]
nav = cash0 + sum(n*float(close[t]) for t, n in hold.items())
print("as_of", asof, "NAV(11/06 close) %.0f" % nav, "(evaluation report: 806,915,359)", "cash %.4f" % (cash0/nav), "names", len(hold))
W = {t: n*float(close[t])/nav for t, n in hold.items()}
tw = sum(v for t, v in W.items() if t in T.TECH)
print("TECH weight %.4f" % tw)
# ---- ranked candidates
e = f[f.eligible].copy()
e["name"] = pd.read_csv(MAIN/"config/universe_150.csv", encoding="utf-8-sig", dtype=str).set_index("ticker").name.reindex(e.index)
e["rank_rs5"] = e.rs5.rank(ascending=False); e["rank_rs2"] = e.rs2.rank(ascending=False)
e["held"] = e.index.isin(list(hold))
e = e.sort_values("rs5", ascending=False)
cols = ["name","sector","r1","r2","r3","r5","r10","r20","rs2","rs5","rs20","vol60","beta_tech","corr_tech","down_cap","up_cap","adv20","big_move_freq60","rank_rs5","rank_rs2","held"]
e[cols].to_csv(HERE/"results/ranked_candidates_20261106.csv", encoding="utf-8-sig")
excluded = f[(~f.is_tech_label) & ~f.eligible]
excluded.assign(reason=np.where(excluded.corr_tech > S.CORR_MAX, "tech-linked corr>0.55", np.where(excluded.adv20 < S.ADV_MIN, "ADV<0.5bn", "limit/price filter"))).to_csv(HERE/"results/excluded_nontech_20261106.csv", encoding="utf-8-sig")
print("eligible non-tech:", len(e), "| non-tech label but excluded:", len(excluded))
print(e[["name","r1","r2","r5","rs5","rs2","vol60","corr_tech","adv20"]].head(10).round(3).to_string())
# ---- Active Share setup
etfs = [r["etf_code"] for r in csv.DictReader(open(MAIN/"config/active_etf_list.csv", encoding="utf-8-sig"))]
eh = pd.read_parquet(MAIN/"data/history/etf_holdings.parquet"); eh = eh[eh.synthetic == False]; ld = eh.date.max(); eh = eh[eh.date == ld]
bench = {k: {str(r.ticker): Decimal(str(r.weight)) for r in g.itertuples()} for k, g in eh.groupby("etf")}
def AS(w, c):
    r = compute_official_active_share({t: Decimal(str(v)) for t, v in w.items()}, bench, etfs, port_cash=Decimal(str(c)), include_cash=False)
    return float(r.minimum_active_share)*100, r.benchmark_ticker, len(r.per_etf)
print("Active Share control %.2f (min ETF %s, %d ETFs with data, benchmark date %s)" % (*AS(W, cash0/nav), ld))
nmax = 30 - len(hold)
sel = S.select(f, "S1_RS5", nmax)
print("selected (S1_RS5, N=%d):" % nmax, sel)
rows = []
for x in (0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60):
    # lots: sell TECH pro rata, buy selected equal weight
    sell_val = x*nav
    sells = {}
    for t, n in hold.items():
        if t in T.TECH:
            q = int(round((n*float(close[t])/ (tw*nav)) * sell_val / float(close[t]) / 1000.0)) * 1000
            sells[t] = min(q, n)
    proceeds = sum(q*float(close[t]) for t, q in sells.items())
    per = proceeds / len(sel)
    buys = {t: int(per // (float(close[t])*1000)) * 1000 for t in sel}
    spent = sum(q*float(close[t]) for t, q in buys.items())
    new = {t: n for t, n in hold.items()}
    for t, q in sells.items(): new[t] -= q
    for t, q in buys.items(): new[t] = new.get(t, 0) + q
    new = {t: n for t, n in new.items() if n > 0}
    cost_leg = proceeds*(FEE+TAX) + spent*FEE
    cash1 = cash0 + proceeds - spent - cost_leg
    nw = {t: n*float(close[t])/nav for t, n in new.items()}
    part = {t: buys[t]*float(close[t])/data.close.index.size*0 + buys[t]*float(close[t])/f.adv20[t] for t in sel}
    a, who, k = AS(nw, cash1/nav)
    ok = (20 <= len(new) <= 30) and max(nw.get(t, 0) for t in nw if t != "2330") <= 0.10 + 1e-9 and cash1/nav < 0.25
    rows.append(dict(x_req=x, sold_nav_pct=round(proceeds/nav*100, 2), bought_nav_pct=round(spent/nav*100, 2), names=len(new), tech_after_pct=round(sum(v for t, v in nw.items() if t in T.TECH)*100, 2),
                     cash_after_pct=round(cash1/nav*100, 2), max_weight_pct=round(max(nw.values())*100, 2), max_new_name_pct=round(max(nw[t] for t in sel)*100, 2),
                     active_share_min_pct=round(a, 2), as_min_etf=who, cost_roundtrip_pct=round(2*cost_leg/nav*100, 3), turnover_roundtrip_pct=round(2*(proceeds+spent)/nav*100, 1),
                     max_adv_participation_pct=round(max(part.values())*100, 2), compliant=bool(ok)))
    if x in (0.20, 0.30):
        json.dump({"x": x, "asof": str(asof), "price_basis": "2026-11-06 close (quantities to be re-derived at the 11/09 07:30 run; VWAP unknown)",
                   "sell": {t: int(q) for t, q in sells.items() if q > 0}, "buy": {t: int(q) for t, q in buys.items() if q > 0},
                   "exit_orders_next_day": "mirror: sell the bought lots, buy back the sold lots (D-Plan of 2026-11-10 for a 1-day hold; 2026-11-11 for 2 days)"},
                  open(HERE/f"results/orders_x{int(x*100)}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
d = pd.DataFrame(rows); d.to_csv(HERE/"results/live_whatif43.csv", index=False)
pd.set_option("display.width", 250); print(d.to_string(index=False))
print("selected names:", [(t, str(e.name.get(t, '')) ) for t in sel])
