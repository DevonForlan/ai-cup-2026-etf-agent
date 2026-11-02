"""RESEARCH ONLY (Issue #14 round 2). Robustness of the one variant that passed the pre-registered gates (R1_F9b), the
extension windows (B), sensitivity (reported, never used to select) and the post-hoc actual competition path (n=1).
   python research\\midcomp_reeval\\extra.py -> results/extra_*.csv + results/EXTRA.md"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import study as S  # noqa: E402
import lab as L  # noqa: E402
import analyze_midcomp as A  # noqa: E402
from run_frozen_windows import windows  # noqa: E402

warnings.filterwarnings("ignore")
OUT, INIT = S.OUT, S.INIT


def f9_custom(k: int, power: float):
    def fn(i, d, w):
        names = sorted(w, key=lambda t: -w[t])[:k] if len(w) > k else list(w)
        base = {t: w[t] ** power for t in names}
        return L.enforce(base, sum(w.values()))
    return fn


def main() -> int:
    data = L.Data()
    wsA, wsB = windows("DENSE24"), A.ws_B()
    variants = S.make_variants(data)
    # ---- 1. F9b / C25_CONC / R1_F1b on the shifted extension windows (B) + sensitivity of the concentration idea
    sens = {"F9b(top20,w^2)": f9_custom(20, 2.0), "top20,w^1": f9_custom(20, 1.0), "top20,w^3": f9_custom(20, 3.0),
            "top24,w^2": f9_custom(24, 2.0), "top15,w^2(<20 names: INVALID officially)": f9_custom(15, 2.0)}
    rows = []
    for tag, ws in (("A", wsA), ("B", wsB)):
        for w in ws:
            base = S.book(100, w["start"], data)
            if base is None:
                continue
            days = base["days"]
            books = {"A1": S.book(1, w["start"], data), "A5": S.book(5, w["start"], data)}
            pool = S.pool_paths(days, data)
            t12, t30 = np.quantile(pool[:, -1], 1 - S.TOP12), np.quantile(pool[:, -1], 1 - S.TOP30)
            pols = {"BASE": None, "R1_F9b": variants["R1_F9b"](), "C25_CONC": variants["C25_CONC"](), "R1_F1b": variants["R1_F1b"]()}
            pols.update({f"SENS {k}": S.Round1(fn) for k, fn in sens.items()})
            for nm, pol in pols.items():
                r = S.replay2(days, base, data, pol, books, pool)
                m = S.metrics(r["nav"])
                rows.append({"src": tag, "start": w["start"], "period": w["period"], "variant": nm, "ret": m["ret"], "mdd": m["mdd"],
                             "turnover": r["turnover"], "cost": r["cost"], "viol": r["viol_official"],
                             "top12": int(m["ret"] > t12), "top30": int(m["ret"] > t30)})
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "extra_windows.csv", index=False)
    out = []
    for tag in ("A", "B"):
        g = d[d.src == tag]
        base = g[g.variant == "BASE"].set_index("start")
        for v in g.variant.unique():
            if v == "BASE":
                continue
            x = g[g.variant == v].set_index("start")
            ex = x.ret - base.ret.loc[x.index]
            for per, sel in (("ALL", x.index), ("DISCOVERY", x.index[x.period == "DISCOVERY"]), ("OOS", x.index[x.period == "OOS"]),
                             ("OOS_first_half", x.index[x.period == "OOS"][:len(x.index[x.period == "OOS"]) // 2]),
                             ("OOS_second_half", x.index[x.period == "OOS"][len(x.index[x.period == "OOS"]) // 2:])):
                e = ex.loc[sel]
                out.append({"src": tag, "variant": v, "sample": per, "n": len(e), "ex_mean_pp": e.mean() * 100, "ex_median_pp": e.median() * 100,
                            "better_pct": (e > 1e-9).mean() * 100, "p_signflip": L.signflip_p(e.to_numpy()) if len(e) else np.nan,
                            "turnover_add": (x.turnover.loc[sel] - base.turnover.loc[sel]).mean(),
                            "cost_add_pct_nav": (x.cost.loc[sel] - base.cost.loc[sel]).mean() / INIT * 100,
                            "mdd_add_pp": (x.mdd.loc[sel] - base.mdd.loc[sel]).mean() * 100,
                            "worst_pp": x.ret.loc[sel].min() * 100, "base_worst_pp": base.ret.loc[sel].min() * 100,
                            "top30_x": x.top30.loc[sel].mean() * 100, "top30_base": base.top30.loc[sel].mean() * 100,
                            "viol_windows": int((x.viol.loc[sel] > 0).sum())})
    o = pd.DataFrame(out)
    o.to_csv(OUT / "extra_robustness.csv", index=False)
    # by calendar half-year for F9b on A+B pooled
    f = d[d.variant.isin(["BASE", "R1_F9b"])].copy()
    f["half"] = f.start.str[:4] + "H" + np.where(f.start.str[5:7].astype(int) <= 6, "1", "2")
    pv = f.pivot_table(index=["src", "start", "half"], columns="variant", values="ret").reset_index()
    pv["ex"] = pv.R1_F9b - pv.BASE
    h = pv.groupby(["src", "half"]).agg(n=("ex", "size"), ex_mean_pp=("ex", lambda x: x.mean() * 100), better_pct=("ex", lambda x: (x > 0).mean() * 100),
                                         base_mean_pp=("BASE", lambda x: x.mean() * 100)).reset_index()
    h.to_csv(OUT / "extra_f9b_by_half_year.csv", index=False)
    # ---- 2. actual competition path (post-hoc, n=1, 5 trading days from 2026-10-27)
    s0 = "2026-10-27"
    base = S.book(100, s0, data)
    days = base["days"]
    books = {"A1": S.book(1, s0, data), "A5": S.book(5, s0, data)}
    pool = S.pool_paths(days, data)
    rows = []
    for f_ in A.FREQS:
        bk = S.book(f_, s0, data)
        if bk is not None:
            m = S.metrics(bk["nav"])
            rows.append({"variant": f"A{f_}", "ret_pct": m["ret"] * 100, "mdd_pct": m["mdd"] * 100,
                         "pool_pctile": float((pool[:, -1] < m["ret"]).mean() * 100)})
    for nm, mk in [("BASE", lambda: None)] + list(variants.items()):
        r = S.replay2(days, base, data, mk(), books, pool)
        m = S.metrics(r["nav"])
        rows.append({"variant": nm, "ret_pct": m["ret"] * 100, "mdd_pct": m["mdd"] * 100,
                     "pool_pctile": float((pool[:, -1] < m["ret"]).mean() * 100), "fired_day": r["events"][0] if r["events"] else -1})
    pd.DataFrame(rows).to_csv(OUT / "extra_actual_path.csv", index=False)
    print(o.round(2).to_string(index=False))
    print(h.round(2).to_string(index=False))
    print(pd.DataFrame(rows).round(2).to_string(index=False), "days", days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
