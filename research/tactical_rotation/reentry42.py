"""RESEARCH ONLY (Issue #42) Task D: pre-registered re-entry rule R on the broad-sell-off events (T3, x = 20/30/40 %, 24 days).
R: hold >= 3 days; re-enter on 2 consecutive closes with (TECH breadth(20d MA) > 0.50 AND TECH EW 5d ret - universe EW 5d ret > 0);
staged 50 % next day, 100 % the day after; time stop day 10. Daily-rebalanced-to-target approximation, round-trip costs charged."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1]/"research"/"tactical_overlay"))
import study42 as T, lab as L
data = L.Data(); tr, amt = T.build(data); bk = T.books_by_date(data)
c = data.close; idx = list(c.index); ev = [pd.Timestamp(x).strftime("%Y-%m-%d") for x in pd.read_csv(T.OUT/"event_dates.csv").entry]
tech = [t for t in T.TECH if t in c.columns]
ma = c.rolling(20).mean(); breadth = (c[tech] > ma[tech]).mean(axis=1)
t5 = (c[tech]/c[tech].shift(5)-1).mean(axis=1); u5 = (c/c.shift(5)-1).mean(axis=1)
sig = (breadth > 0.5) & ((t5 - u5) > 0)
def daily(i, wts, k):   # return of day i+k from fixed weights (close-to-close; day 0 = entry VWAP->close)
    if k == 0:
        return sum(w*(float(c.iloc[i][t])/float(data.vwap.iloc[i][t])-1) for t, w in wts.items())
    return sum(w*float(tr[t].iloc[i+k]) for t, w in wts.items())
rows = []
for e in ev:
    i = idx.index(e)
    if e not in bk or i+24 >= len(idx): continue
    w, cash = T.alloc(bk[e], data, e)
    st = T.structures(data, amt, i, 30-len(w))
    for x in (0.2, 0.3, 0.4):
        r = T.rotate(w, cash, x, st["T3_2412+BASKET"])
        if r is None: continue
        nw, cost, turn, sold = r
        # state: fraction rotated f_k in [0,1]; f=1 right after entry
        f, ok, back_at, nav_h, nav_r, nav_n = 1.0, 0, None, 1.0, 1.0, 1.0
        recost = 0.0
        path = []
        for k in range(0, 25):
            wk = {t: (1-f)*w.get(t, 0) + f*nw.get(t, 0) for t in set(w)|set(nw)}
            rr = daily(i, wk, k)
            nav_r *= 1+rr; nav_h *= 1+daily(i, w, k); nav_n *= 1+daily(i, nw, k)
            # signal at close of day k decides weights for day k+1
            if k >= 3 and f == 1.0 and back_at is None:
                ok = ok+1 if bool(sig.iloc[i+k]) else 0
                if ok >= 2 or k >= 10: back_at = k
            if back_at is not None:
                step = k - back_at
                f_new = 0.5 if step == 0 else 0.0
                if f_new < f: recost += (f - f_new) * x * (T.FEE*2 + T.TAX*0) * 1.0; f = f_new
            if back_at is not None and k > back_at: f = 0.0
        rows.append(dict(entry=e, size=x, period="DISCOVERY" if e < "2025-07-01" else "OOS", back_day=back_at,
                         hold24=nav_h-1, never_back24=nav_n-1-cost, rule_R24=nav_r-1-cost-recost,
                         ex_rule_pp=(nav_r-1-cost-recost-(nav_h-1))*100, ex_never_pp=(nav_n-1-cost-(nav_h-1))*100))
d = pd.DataFrame(rows); d.to_csv(T.OUT/"reentry42.csv", index=False)
g = d.groupby(["size","period"]).agg(n=("entry","size"), rule_R_vs_frozen_pp=("ex_rule_pp","mean"), never_back_vs_frozen_pp=("ex_never_pp","mean"), hit_R=("ex_rule_pp", lambda s: (s>0).mean()*100), med_back_day=("back_day","median")).round(2)
print(g.to_string()); print(d.back_day.value_counts(dropna=False).sort_index().to_string())
