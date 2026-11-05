"""RESEARCH ONLY (Issue #41). Sector-diversification overlays vs the frozen buy-and-hold control. See PRE_REGISTRATION.md."""
from __future__ import annotations
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT, ROOT / "research" / "tactical_overlay", ROOT / "research" / "midcomp_reeval"):
    sys.path.insert(0, str(p))
warnings.filterwarnings("ignore")
import study as S  # noqa: E402
import lab as L  # noqa: E402
import analyze_midcomp as A  # noqa: E402
from run_frozen_windows import windows  # noqa: E402

OUT = HERE / "results"; OUT.mkdir(exist_ok=True)
INIT = S.INIT
TECH_S = {"半導體業", "電腦及週邊設備業", "電子零組件業", "其他電子業", "通信網路業", "光電業", "電子通路業"}
SM = L.sector_map()
TECH = {t for t, s in SM.items() if s in TECH_S}
MAXN = 28


def _redistribute(w, a1, group, new_group_total, to_cash_frac=0.0):
    """scale `group` names to new_group_total, send the excess to non-group receivers (A1 weights) / cash."""
    gw = sum(v for t, v in w.items() if t in group)
    if gw <= new_group_total + 1e-9:
        return None
    k = new_group_total / gw if gw > 0 else 0
    out = {t: (v * k if t in group else v) for t, v in w.items()}
    excess = (gw - new_group_total) * (1 - to_cash_frac)
    rec = {t: v for t, v in (a1 or {}).items() if t not in group and v > 0}
    cur = {t: v for t, v in w.items() if t not in group}
    pool = dict(sorted({**rec, **{t: rec.get(t, v) for t, v in cur.items()}}.items(), key=lambda x: -x[1]))
    keep = {t for t in w if t not in group} | set(list(rec)[: max(0, MAXN - len(w))])
    pool = {t: v for t, v in pool.items() if t in keep}
    ps = sum(pool.values())
    if ps <= 0:
        return L.enforce(out, sum(out.values()))
    for t, v in pool.items():
        out[t] = out.get(t, 0) + excess * v / ps
    inv = sum(out.values())
    return L.enforce(out, min(inv, 1 - L.CASH_MAX + 0.24 + 1e-6 if False else inv))


class Pol:
    def __init__(self, kind, data, param=None, group=None):
        self.kind, self.data, self.param, self.group = kind, data, param, group

    def tech_breadth(self, d):
        c = self.data.close
        i = c.index.get_loc(d)
        if i < 21:
            return 1.0
        cols = [t for t in TECH if t in c.columns]
        x = c.iloc[i - 1, :][cols]; ma = c.iloc[i - 21:i - 1, :][cols].mean()
        return float((x > ma).mean())

    def act(self, i, d, ctx):
        w = ctx["base_w"]; a1 = ctx["alt_w"]("A1")
        k, p = self.kind, self.param
        r = None
        if k == "B_CAP":
            r = _redistribute(w, a1, TECH, p)
        elif k == "C_BREADTH":
            if self.tech_breadth(d) < p:
                r = _redistribute(w, a1, TECH, 0.60)
        elif k == "D_FLOOR":
            tg = sum(v for t, v in w.items() if t in TECH)
            nt = sum(w.values()) - tg
            if nt < p:
                r = _redistribute(w, a1, TECH, tg - (p - nt))
        elif k == "D_N":
            nn = [t for t in w if t not in TECH]
            rec = [t for t, v in sorted((a1 or {}).items(), key=lambda x: -x[1]) if t not in TECH and t not in w]
            need = p - len(nn)
            if need > 0 and rec:
                add = rec[:need]
                fund = 0.02 * len(add)
                tg = sum(v for t, v in w.items() if t in TECH)
                out = {t: (v * (tg - fund) / tg if t in TECH else v) for t, v in w.items()}
                for t in add:
                    out[t] = 0.02
                r = L.enforce(out, sum(out.values()))
        elif k == "E_HYBRID":
            r = _redistribute(w, a1, TECH, p, to_cash_frac=0.5)
        elif k == "P_RANDOM":
            g = self.group
            cap = self.param
            r = _redistribute(w, a1, g, cap)
        elif k == "P_CHASE":
            c = self.data.close; j = c.index.get_loc(d)
            if j >= 6:
                ret = c.iloc[j - 1] / c.iloc[j - 6] - 1
                t_r = ret[[t for t in TECH if t in ret.index]].mean(); n_r = ret[[t for t in c.columns if t not in TECH]].mean()
                if n_r > t_r:
                    r = _redistribute(w, a1, TECH, max(sum(v for t, v in w.items() if t in TECH) - 0.10, 0))
        return None if r is None else ("w", r)


def variants(data):
    v = {f"B_CAP{c}": (lambda c=c: Pol("B_CAP", data, c / 100)) for c in (55, 60, 65, 70)}
    v["C_BREADTH40"] = lambda: Pol("C_BREADTH", data, 0.40)
    v["C_BREADTH30"] = lambda: Pol("C_BREADTH", data, 0.30)
    v["D_FLOOR30"] = lambda: Pol("D_FLOOR", data, 0.30)
    v["D_N8"] = lambda: Pol("D_N", data, 8)
    v["E_HYBRID65"] = lambda: Pol("E_HYBRID", data, 0.65)
    v["P_CHASE"] = lambda: Pol("P_CHASE", data)
    return v


def tech_share(w):
    return sum(x for t, x in w.items() if t in TECH)


def run_window(w, data, vs, nseed=5):
    base = S.book(100, w["start"], data)
    if base is None:
        return []
    days = base["days"]
    books = {"A1": S.book(1, w["start"], data)}
    if books["A1"] is None:
        return []
    pool = None
    rows = []
    def go(nm, pol, seed=-1):
        r = S.replay2(days, base, data, pol, books, pool)
        m = S.metrics(r["nav"])
        rows.append({"src": w["set"], "start": w["start"], "period": w["period"], "variant": nm, "seed": seed, "ret": m["ret"], "mdd": m["mdd"],
                     "turnover": r["turnover"], "cost": r["cost"], "viol": r["viol_official"], "end_nav": r["nav"][-1]})
    go("BASE", None)
    for nm, mk in vs.items():
        go(nm, mk())
    # random-group placebo: same mechanism on a random 50 % group, cap = 0.83 x its day-0 weight
    uni = [t for t in data.close.columns]
    sh = base["shares"][0]; vw = data.vwap.loc[days[0]]
    nav0 = sum(n * float(vw[t]) for t, n in sh.items()) + base["cash"][0]
    w0 = {t: n * float(vw[t]) / nav0 for t, n in sh.items()}
    for s in range(nseed):
        rng = np.random.default_rng(41 * 1000 + s + int(w["start"].replace("-", "")) % 997)
        grp = set(rng.choice(uni, size=len(uni) // 2, replace=False))
        gw = sum(v for t, v in w0.items() if t in grp)
        go("P_RANDOM_CAP", Pol("P_RANDOM", data, 0.83 * gw, group=grp), seed=s)
    return rows


def main():
    import time
    data = L.Data()
    vs = variants(data)
    out = []
    t0 = time.time()
    for tag, ws in (("A", windows("DENSE24")), ("B", A.ws_B())):
        for n, w in enumerate(ws):
            out += run_window(w, data, vs)
            if n % 10 == 0:
                print(tag, n, len(ws), round(time.time() - t0), flush=True)
    pd.DataFrame(out).to_csv(OUT / "windows41.csv", index=False)
    # live 5-day path (post-hoc, n=1)
    s0 = "2026-10-27"; base = S.book(100, s0, data); live = []
    if base is not None:
        books = {"A1": S.book(1, s0, data)}
        for nm, mk in [("BASE", lambda: None)] + list(vs.items()):
            r = S.replay2(base["days"], base, data, mk(), books, None); m = S.metrics(r["nav"])
            live.append({"variant": nm, "ret_pct": m["ret"] * 100, "mdd_pct": m["mdd"] * 100})
    pd.DataFrame(live).to_csv(OUT / "live_path41.csv", index=False)
    print(pd.DataFrame(live).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
