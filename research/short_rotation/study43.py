"""RESEARCH ONLY (Issue #43). 1-2 trading-day forced non-tech rotation: event study + live ranking. See PRE_REGISTRATION.md.
Timing: signal at close of day d, entry = VWAP of d+1 (Mon 11/09), exit = VWAP of d+1+h, outcome = NAV at close of d+1+h."""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT, ROOT / "research" / "tactical_overlay", ROOT / "research" / "midcomp_reeval", ROOT / "research" / "tactical_rotation"):
    sys.path.insert(0, str(p))
warnings.filterwarnings("ignore")
import lab as L  # noqa: E402
import study42 as T  # noqa: E402

OUT = HERE / "results"
OUT.mkdir(exist_ok=True)
FEE, TAX = T.FEE, T.TAX
TECH, SM = T.TECH, T.SM
H = (1, 2)
SIZES = (0.10, 0.20, 0.30, 0.40)
CORR_MAX, ADV_MIN = 0.55, 0.5e9


def features(data, amt, d_idx):
    """PIT features at close of index d_idx (decision information)."""
    c, rt = data.close, data.ret
    tech = [t for t in TECH if t in rt.columns]
    tech_ret = rt[tech].mean(axis=1)
    ew = rt.median(axis=1)
    lo, hi = d_idx - 119, d_idx + 1
    f = pd.DataFrame(index=c.columns)
    for n in (1, 2, 3, 5, 10, 20):
        f[f"r{n}"] = c.iloc[d_idx] / c.iloc[d_idx - n] - 1
    ewu = {n: float((c.iloc[d_idx] / c.iloc[d_idx - n] - 1).median()) for n in (1, 2, 3, 5, 10, 20)}
    for n in (1, 2, 5, 20):
        f[f"rs{n}"] = f[f"r{n}"] - ewu[n]
    sub = rt.iloc[lo:hi]
    tr_ = tech_ret.iloc[lo:hi]
    sx = sub.fillna(0.0).to_numpy(); tx = tr_.to_numpy()
    sc, tc = sx - sx.mean(axis=0), tx - tx.mean()
    cov = (sc * tc[:, None]).sum(axis=0) / (len(tx) - 1)
    f["beta_tech"] = cov / tx.var(ddof=1)
    f["corr_tech"] = cov / (sx.std(axis=0, ddof=1) * tx.std(ddof=1) + 1e-12)
    f["vol60"] = rt.iloc[d_idx - 59:d_idx + 1].std()
    f["adv20"] = amt.iloc[d_idx - 19:d_idx + 1].mean()
    f["big_move_freq60"] = (rt.iloc[d_idx - 59:d_idx + 1].abs() > 0.05).mean()
    dn = (tr_ < -0.015)
    up = (tr_ > 0.015)
    f["down_cap"] = sub[dn.reindex(sub.index).fillna(False)].mean() / tr_[dn].mean() if dn.any() else np.nan
    f["up_cap"] = sub[up.reindex(sub.index).fillna(False)].mean() / tr_[up].mean() if up.any() else np.nan
    f["sector"] = pd.Series(SM)
    f["is_tech_label"] = f.index.isin(TECH)
    f["eligible"] = (~f.is_tech_label) & (f.corr_tech <= CORR_MAX) & (f.adv20 >= ADV_MIN) & (f.r1 > -0.095) & (f.r1 < 0.095)
    return f


def select(f, rule, n, rng=None):
    e = f[f.eligible]
    if len(e) == 0 or n <= 0:
        return []
    if rule == "S1_RS5":
        return list(e.rs5.sort_values(ascending=False).index[:n])
    if rule == "S2_RS2":
        return list(e.rs2.sort_values(ascending=False).index[:n])
    if rule == "S3_LOWVOL":
        return list(e.vol60.sort_values().index[:n])
    if rule == "S4_LOWBETA":
        return list(e.beta_tech.sort_values().index[:n])
    if rule == "S5_EWNT":
        return list(e.adv20.sort_values(ascending=False).index[:28])
    if rule == "S6_RANDOM":
        return list(rng.choice(list(e.index), size=min(n, len(e)), replace=False))
    if rule == "S8_42BASKET":
        liq = f[(~f.is_tech_label) & (f.index != "2412")].adv20.sort_values(ascending=False)
        return (["2412"] + list(liq.index[:max(n - 1, 0)]))[:n]
    raise ValueError(rule)


def path_ret(data, tr, i, h, w, nw, cost):
    """return (NAV at close of i+h vs NAV at VWAP of i) of: hold nw from VWAP(i) to VWAP(i+h), then original weights w."""
    c, v = data.close, data.vwap
    A = 0.0
    for t, wt in nw.items():
        fac = float(c.iloc[i][t]) / float(v.iloc[i][t])
        for k in range(1, h):
            fac *= 1 + float(tr[t].iloc[i + k])
        fac *= float(v.iloc[i + h][t]) / float(c.iloc[i + h - 1][t])
        A += wt * (fac - 1)
    B = sum(wt * (float(c.iloc[i + h][t]) / float(v.iloc[i + h][t]) - 1) for t, wt in w.items())
    return (1 + A) * (1 + B) - 1 - cost


def rotate_sel(w, cash, x, names, to_cash=False):
    r = T.rotate(w, cash, x, names, to_cash)
    if r is None:
        return None
    nw, cost1, turn, sold = r
    return nw, 2 * cost1, turn * 2, sold      # entry + exit legs (exit mirrors the entry)


def events(data, kind):
    rt = data.ret
    ew = rt.median(axis=1)
    tech = rt[[t for t in TECH if t in rt.columns]].mean(axis=1)
    if kind == "E1":
        s = ew <= -0.015
    elif kind == "E2":
        s = ew <= -0.02
    elif kind == "E3":
        s = ew <= -0.01
    elif kind == "E4":
        s = tech <= -0.025
    elif kind == "E5":
        s = (ew + ew.shift(1)) <= -0.03
    idx = list(rt.index)
    out, last = [], -99
    for i, flag in enumerate(s.to_numpy()):
        if flag and i - last >= 3 and i + 1 < len(idx) and i >= 125:
            out.append(i)
            last = i
    return out


def main():
    data = L.Data()
    tr, amt = T.build(data)
    bk = T.books_by_date(data)
    idx = list(data.close.index)
    rng = np.random.default_rng(43)
    uni = list(data.close.columns)
    rules = ["S1_RS5", "S2_RS2", "S3_LOWVOL", "S4_LOWBETA", "S5_EWNT", "S8_42BASKET"]
    sets = {k: events(data, k) for k in ("E1", "E2", "E3", "E4", "E5")}
    sets["CONTROL"] = [i for i in range(125, len(idx) - 4, 4)]
    rows = []
    cache = {}
    done = 0
    for kind, dlist in sets.items():
        for d_idx in dlist:
            done += 1
            if done % 25 == 0:
                print(kind, done, flush=True)
            i = d_idx + 1
            e = idx[i]
            if e not in bk or i + 2 >= len(idx):
                continue
            key = i
            if key not in cache:
                w, cash = T.alloc(bk[e], data, e)
                f = features(data, amt, d_idx)
                pool = {}
                for h in H:
                    fac = (data.close.iloc[i] / data.vwap.iloc[i]).to_numpy() * np.prod(1 + tr.iloc[i + 1:i + h + 1].to_numpy(), axis=0) - 1
                    pool[h] = np.array([0.9 * np.nanmean(fac[rng.choice(len(uni), size=int(rng.integers(20, 31)), replace=False)]) for _ in range(200)])
                cache[key] = (w, cash, f, pool,
                              {h: T.fwd(data, tr, i, h, w) for h in H})
            w, cash, f, pool, base = cache[key]
            per = "DISCOVERY" if e < "2025-07-01" else "OOS"
            nmax = 30 - len(w)
            tw = sum(v for t, v in w.items() if t in TECH)
            variants = []
            for x in SIZES:
                for r in rules:
                    variants.append((r, x, select(f, r, nmax), False))
                variants.append(("S7_CASH", x, [], True))
            for s in range(10):
                variants.append((f"S6_RANDOM_{s}", 0.30, select(f, "S6_RANDOM", nmax, rng), False))
                variants.append((f"S6_RANDOM_{s}", 0.20, select(f, "S6_RANDOM", nmax, rng), False))
            for r, x, names, to_cash in variants:
                res = rotate_sel(w, cash, x, names, to_cash) if (names or to_cash) else None
                for h in H:
                    row = dict(set=kind, entry=e, period=per, struct=r, size=x, h=h, base=base[h], tech_w=tw)
                    if res is None:
                        row["infeasible"] = 1
                    else:
                        nw, cost, turn, sold = res
                        rr = path_ret(data, tr, i, h, w, nw, cost)
                        sleeve = {t: v for t, v in nw.items() if t in names}
                        row.update(ret=rr, cost=cost, turnover=turn, sold=sold, rank=float(np.mean(pool[h] < rr)),
                                   base_rank=float(np.mean(pool[h] < base[h])), n_names=len(nw))
                    rows.append(row)
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "events43.csv", index=False)
    pd.DataFrame({k: [idx[i + 1] for i in v] for k, v in sets.items() if k != "CONTROL"}.items() and []).to_csv(OUT / "_x.csv") if False else None
    pd.Series({k: len(v) for k, v in sets.items()}).to_csv(OUT / "event_counts.csv")
    print({k: len(v) for k, v in sets.items()}, len(d), "rows")


if __name__ == "__main__":
    main()
