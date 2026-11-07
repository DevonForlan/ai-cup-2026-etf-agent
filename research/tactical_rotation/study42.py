"""RESEARCH ONLY (Issue #42). Event study of tactical rotation out of TECH. See PRE_REGISTRATION.md."""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT, ROOT / "research" / "tactical_overlay", ROOT / "research" / "midcomp_reeval"):
    sys.path.insert(0, str(p))
warnings.filterwarnings("ignore")
import study as S  # noqa: E402
import lab as L  # noqa: E402
import analyze_midcomp as A  # noqa: E402
from run_frozen_windows import windows  # noqa: E402

OUT = HERE / "results"
OUT.mkdir(exist_ok=True)
FEE, TAX = 0.001425, 0.003
TECH_S = {"半導體業", "電腦及週邊設備業", "電子零組件業", "其他電子業", "通信網路業", "光電業", "電子通路業"}
SM = L.sector_map()
TECH = {t for t, s in SM.items() if s in TECH_S}
SEMI = {t for t, s in SM.items() if s == "半導體業"}
FIN = {t for t, s in SM.items() if s == "金融保險業"}
H = (3, 5, 10, 24)
SIZES = (0.10, 0.20, 0.30, 0.40)
CAP, TSMC_CAP, CASH_MAX = 0.10, 0.25, 0.25


def cap_of(t):
    return TSMC_CAP if t == "2330" else CAP


def build(data):
    c = data.close
    tr = data.ret.copy()
    for (d, t), cd in data.div.items():
        if d in tr.index and t in tr.columns:
            i = tr.index.get_loc(d)
            if i > 0 and not pd.isna(c.iloc[i - 1][t]):
                tr.at[d, t] = (0 if pd.isna(tr.at[d, t]) else tr.at[d, t]) + cd / c.iloc[i - 1][t]
    amt = data.volume.reindex(c.index) * c
    return tr.fillna(0.0), amt


def books_by_date(data):
    out = {}
    for ws in (windows("DENSE24"), A.ws_B()):
        for w in ws:
            b = S.book(100, w["start"], data)
            if b is None:
                continue
            for i, d in enumerate(b["days"]):
                out.setdefault(d, (b["shares"][i], b["cash"][i]))
    return out


def fwd(data, tr, i, h, wts):
    """return of fixed entry weights from VWAP(day i) to close(day i+h), dividends included."""
    out = 0.0
    for t, w in wts.items():
        entry = float(data.close.iloc[i][t]) / float(data.vwap.iloc[i][t])
        out += w * (entry * float(np.prod(1 + tr[t].iloc[i + 1:i + h + 1].to_numpy())) - 1)
    return out


def path_mdd(data, tr, i, h, wts):
    cum = {t: float(data.close.iloc[i][t]) / float(data.vwap.iloc[i][t]) for t in wts}
    nav = [1.0]
    for k in range(1, h + 1):
        for t in wts:
            cum[t] *= 1 + float(tr[t].iloc[i + k])
        nav.append(1 + sum(w * (cum[t] - 1) for t, w in wts.items()))
    return L.path_metrics(nav)["mdd"]


def alloc(book, data, e):
    sh, cash = book
    vw = data.vwap.loc[e]
    nav = sum(n * float(vw[t]) for t, n in sh.items()) + cash
    return {t: n * float(vw[t]) / nav for t, n in sh.items()}, cash / nav


def rotate(w, cash, x, sleeve, to_cash=False):
    """Sell x NAV of TECH pro rata and buy `sleeve` equal weight within caps (or hold the proceeds as cash).
    Returns (weights, cost_nav, turnover) or None if the result breaks 20-30 names / cash < 25 %."""
    tw = sum(v for t, v in w.items() if t in TECH)
    x = min(x, tw)
    if to_cash:
        x = min(x, max(CASH_MAX - 0.003 - cash, 0))
    new = {t: (v * (1 - x / tw) if t in TECH else v) for t, v in w.items()}
    rem = x
    if not to_cash:
        for _ in range(12):
            if rem <= 1e-9:
                break
            open_ = [t for t in sleeve if cap_of(t) - new.get(t, 0) > 1e-9]
            if not open_:
                break
            share = rem / len(open_)
            for t in open_:
                a = min(share, cap_of(t) - new.get(t, 0))
                new[t] = new.get(t, 0) + a
                rem -= a
    bought = x - rem if not to_cash else 0.0
    cost = x * (FEE + TAX) + bought * FEE
    cash_new = cash + x - bought - cost
    if len(new) > 30 or len(new) < 20 or cash_new >= CASH_MAX:
        return None
    return new, cost, x + bought, x


def structures(data, amt, i, nmax):
    adv = amt.iloc[i - 20:i].mean()
    nonT = [t for t in data.close.columns if t not in TECH and t != "2412"]
    liq = adv[nonT].sort_values(ascending=False)
    nmax = max(nmax, 1)
    top = list(liq.index[:nmax])
    vol60 = data.ret.iloc[i - 60:i].std()
    lowvol = list(vol60[list(liq.index[:20])].sort_values().index[:nmax])
    fin = list(adv[[t for t in FIN]].sort_values(ascending=False).index[:nmax])
    return {"T1_2412": ["2412"], "T2_BASKET": top, "T3_2412+BASKET": ["2412"] + top[:max(nmax - 1, 0)], "T4_LOWVOL": lowvol, "T5_FIN": fin}


def events(data):
    ew = data.ret.median(axis=1)
    idx = list(data.close.index)
    ev, last = [], -99
    for i, d in enumerate(idx):
        if ew.iloc[i] <= -0.02 and i - last >= 10 and i + 1 < len(idx):
            ev.append(idx[i + 1])
            last = i
    return ev


def main():
    data = L.Data()
    tr, amt = build(data)
    bk = books_by_date(data)
    idx = list(data.close.index)
    ev = events(data)
    ctrl = idx[61::6]
    rng = np.random.default_rng(42)
    uni = list(data.close.columns)
    nonT_all = [t for t in uni if t not in TECH and t != "2412"]
    rows = []
    for kind, dates in (("EVENT", ev), ("CONTROL", ctrl)):
        for e in dates:
            i = idx.index(e)
            if e not in bk or i + 24 >= len(idx) or i < 61:
                continue
            w, cash = alloc(bk[e], data, e)
            if not w:
                continue
            per = "DISCOVERY" if e < "2025-07-01" else "OOS"
            st = structures(data, amt, i, 30 - len(w))
            pool = {h: [] for h in H}
            for _ in range(300):
                k = int(rng.integers(20, 31))
                nm = list(rng.choice(uni, size=k, replace=False))
                pw = {t: 0.9 / k for t in nm}
                for h in H:
                    pool[h].append(fwd(data, tr, i, h, pw))
            pool = {h: np.array(v) for h, v in pool.items()}
            base = {h: fwd(data, tr, i, h, w) for h in H}
            bmdd = {h: path_mdd(data, tr, i, h, w) for h in (10, 24)}
            common = dict(kind=kind, entry=e, period=per, tech_w=sum(v for t, v in w.items() if t in TECH), cash_w=cash)
            for bn, names in (("EW_UNIV", uni), ("EW_TECH", list(TECH)), ("EW_SEMI", list(SEMI))):
                bw = {t: 1 / len(names) for t in names}
                for h in H:
                    rows.append({**common, "struct": bn, "size": np.nan, "h": h, "ret": fwd(data, tr, i, h, bw), "base": base[h],
                                 "base_rank": float(np.mean(pool[h] < base[h]))})
            variants = [(s, names, x, False) for s, names in st.items() for x in SIZES]
            variants += [("T7_CASH", [], x, True) for x in SIZES]
            variants += [(f"T6_RANDOM_{s}", list(rng.choice(nonT_all, size=min(6, 30 - len(w)), replace=False)), 0.30, False) for s in range(20)]
            for s, names, x, to_cash in variants:
                r = rotate(w, cash, x, names, to_cash)
                if r is None:
                    for h in H:
                        rows.append({**common, "struct": s, "size": x, "h": h, "ret": np.nan, "base": base[h], "infeasible": 1})
                    continue
                nw, cost, turn, sold = r
                for h in H:
                    rt = fwd(data, tr, i, h, nw) - cost
                    row = {**common, "struct": s, "size": x, "h": h, "ret": rt, "base": base[h], "turnover": turn, "cost": cost,
                           "sold": sold, "rank": float(np.mean(pool[h] < rt)), "base_rank": float(np.mean(pool[h] < base[h]))}
                    if h in (10, 24):
                        row["mdd_delta"] = path_mdd(data, tr, i, h, nw) - bmdd[h]
                    rows.append(row)
    pd.DataFrame(rows).to_csv(OUT / "events42.csv", index=False)
    pd.Series(ev, name="entry").to_csv(OUT / "event_dates.csv", index=False)
    print(len(ev), "events;", len(rows), "rows")


if __name__ == "__main__":
    main()
