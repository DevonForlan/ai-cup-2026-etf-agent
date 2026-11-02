"""RESEARCH ONLY (Issue #14 round 2). Evaluates every pre-registered variant (PRE_REGISTRATION.md §3-§5).
   python research\\midcomp_reeval\\analyze_midcomp.py -> results/*.csv, results/RESULTS.md"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import study as S  # noqa: E402
import lab as L  # noqa: E402
from run_frozen_windows import windows  # noqa: E402

warnings.filterwarnings("ignore")
OUT, RUNS, INIT = S.OUT, S.RUNS, S.INIT
FREQS = [100, 20, 10, 5, 3, 1]
rng = np.random.default_rng(14)


def ws_B():
    from run_frozen_windows import trading_days
    days = trading_days()
    return [{"set": "B", "start": days[i], "end": days[i + 23], "days": 24,
             "period": "DISCOVERY" if days[i] < "2025-07-01" else "OOS"} for i in range(3, len(days) - 23, 6)]


def nav_metrics(run_id: str) -> dict | None:
    p = RUNS / run_id / "daily.csv"
    if not p.exists():
        return None
    d = pd.read_csv(p, encoding="utf-8-sig")
    m = L.path_metrics(d["nav"].astype(float).tolist())
    return {"ret": m["ret"], "mdd": m["mdd"], "worst_1d": m["worst_1d"], "turnover": float(d["turnover"].astype(float).sum()),
            "avg_cash": float(d["cash_ratio"].astype(float).mean())}


# ---------------------------------------------------------------- statistics
def holm(ps: dict) -> dict:
    items = sorted(ps.items(), key=lambda kv: kv[1])
    n, out, run = len(items), {}, 0.0
    for r, (k, p) in enumerate(items):
        run = max(run, min(1.0, (n - r) * p))
        out[k] = run
    return out


def block_ci(x: np.ndarray, block: int = 4, n: int = 4000) -> tuple[float, float]:
    x = np.asarray(x, dtype=float)
    if len(x) < block:
        return (np.nan, np.nan)
    nb = int(np.ceil(len(x) / block))
    starts = np.arange(len(x) - block + 1)
    means = []
    for _ in range(n):
        s = rng.choice(starts, size=nb)
        means.append(np.concatenate([x[i:i + block] for i in s])[:len(x)].mean())
    return (float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975)))


def cvar10(r: np.ndarray) -> float:
    k = max(1, int(np.ceil(0.1 * len(r))))
    return float(np.sort(r)[:k].mean())


def summarize(df: pd.DataFrame, base_name: str, scope: str | None = None) -> pd.DataFrame:
    """df: start, period, variant, ret, mdd, turnover, cost, top12, top30 (one row per window x variant)."""
    rows = []
    base = df[df.variant == base_name].set_index("start")
    for v, g in df.groupby("variant"):
        g = g.set_index("start")
        for per in ("ALL", "DISCOVERY", "OOS"):
            gg = g if per == "ALL" else g[g.period == per]
            bb = base.loc[gg.index]
            ex = gg["ret"] - bb["ret"]
            rows.append({"variant": v, "sample": per, "n": len(gg), "median_ret": gg.ret.median(), "mean_ret": gg.ret.mean(),
                         "hit": (gg.ret > 0).mean(), "mdd_mean": gg.mdd.mean(), "mdd_worst": gg.mdd.max(), "worst_window": gg.ret.min(),
                         "cvar10": cvar10(gg.ret.to_numpy()), "turnover": gg.turnover.mean(), "cost": gg.cost.mean(),
                         "top12": gg.top12.mean(), "top30": gg.top30.mean(),
                         "ex_mean": ex.mean(), "ex_median": ex.median(), "ex_better": (ex > 1e-9).mean(),
                         "p_signflip": L.signflip_p(ex.to_numpy()) if v != base_name else np.nan})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- family A (real pipeline)
def family_a(data: L.Data, ws: list[dict], tag: str) -> pd.DataFrame:
    rows = []
    for w in ws:
        base = S.book(100, w["start"], data)
        if base is None:
            continue
        pool = S.pool_paths(base["days"], data)
        t12, t30 = np.quantile(pool[:, -1], 1 - S.TOP12), np.quantile(pool[:, -1], 1 - S.TOP30)
        for f in FREQS:
            m = nav_metrics(f"A{f}__{w['start']}")
            if m is None:
                continue
            c = pd.read_csv(OUT / (f"rebalance_A{f}.csv" if tag == "A" else f"rebalance_B_A{f}.csv"))
            c = c[c.start == w["start"]]
            rows.append({"start": w["start"], "period": w["period"], "variant": f"A{f}", **m,
                         "cost": float(c.cost.iloc[0]) if len(c) else np.nan, "viol": int(c.violations.iloc[0]) if len(c) else 0,
                         "top12": int(m["ret"] > t12), "top30": int(m["ret"] > t30)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- placebos (D overlays: time-shift; round-1 tilts: name shuffle)
def placebo(data: L.Data, ws: list[dict], name: str, n: int = 20) -> list[float]:
    mk = data.sig["market"]
    out = []
    oos = [w for w in ws if w["period"] == "OOS"]
    for k in range(n):
        shift = int(rng.integers(5, 300))
        if name.startswith("D"):
            cols = {"D1_BREADTH_TREND": lambda d: bool(mk.at[d, "breadth"] < 0.35 and mk.at[d, "ew_trend20"] < 0),
                    "D3_SOX": lambda d: bool(mk.at[d, "SOX_20"] < -0.10) if not pd.isna(mk.at[d, "SOX_20"]) else False}
            vol = mk["ew_vol20"].rolling(250, min_periods=60).quantile(0.8)
            cols["D2_VOL"] = lambda d: bool(mk.at[d, "ew_vol20"] > vol.at[d]) if not pd.isna(vol.at[d]) else False
            cols["D4_ANY"] = lambda d: cols["D1_BREADTH_TREND"](d) or cols["D2_VOL"](d) or cols["D3_SOX"](d)
            f = cols[name]
            dates = data.dates

            def shifted(d, f=f, shift=shift, dates=dates):
                return f(dates[(dates.index(d) - shift) % len(dates)])
            mkpol = lambda: S.Regime(shifted)  # noqa: E731
        else:
            fn = L.overlay_fn(name.replace("R1_", ""), data, rng=np.random.default_rng(1000 + k))
            mkpol = lambda fn=fn: S.Round1(fn)  # noqa: E731
        ex = []
        for w in oos[::2]:                       # every other OOS window (speed); same subset for every placebo
            b = S.book(100, w["start"], data)
            base = S.replay2(b["days"], b, data, None, {}, None)["nav"][-1] / INIT - 1
            r = S.replay2(b["days"], b, data, mkpol(), {}, None)["nav"][-1] / INIT - 1
            ex.append(r - base)
        out.append(float(np.mean(ex)))
    return out


# ---------------------------------------------------------------- recovery
def recovery(data: L.Data, ws: list[dict], variants: dict, band: tuple[float, float]) -> pd.DataFrame:
    rows = []
    for w in ws:
        s = w["start"]
        base = S.book(100, s, data)
        if base is None:
            continue
        days = base["days"]
        books = {"A1": S.book(1, s, data), "A5": S.book(5, s, data)}
        pool = S.pool_paths(days, data)
        t12, t30 = np.quantile(pool[:, -1], 1 - S.TOP12), np.quantile(pool[:, -1], 1 - S.TOP30)
        b = S.replay2(days, base, data, None, books, pool)
        nav = np.array(b["nav"])
        k = next((k for k in (4, 5, 6) if band[0] <= nav[k - 1] / INIT - 1 <= band[1]), None)
        if k is None:
            continue
        forced = {
            "KEEP_FROZEN": None,
            "FOLLOW_A5(rerank 5d)": S.Trigger(lambda c, k=k: c["i"] >= k, S.act_rerank_follow("A5")),
            "FOLLOW_A1(rerank daily)": S.Trigger(lambda c, k=k: c["i"] >= k, S.act_rerank_follow("A1")),
            "HOLD_A1_BOOK(one-off rerank)": S.Trigger(lambda c, k=k: c["i"] >= k, S.act_rerank_hold("A1")),
            "DD_TRIGGER_CASH(cash 24%)": S.Trigger(lambda c, k=k: c["i"] >= k, S.act_cash),
            "TACTICAL_D4": variants["D4_ANY"](),
            "R1_F9b(concentrate)": variants["R1_F9b"](),
            "RANK_C25_RERANK": variants["C25_RERANK"](), "RANK_C25_CASH": variants["C25_CASH"](),
            "RANK_C25_CONC": variants["C25_CONC"](),
        }
        for name, pol in forced.items():
            r = S.replay2(days, base, data, pol, books, pool)
            nv = np.array(r["nav"])
            fin = nv[-1] / INIT - 1
            rem = nv[-1] / nv[k - 1] - 1
            rows.append({"start": s, "period": w["period"], "k": k, "k_ret": float(nav[k - 1] / INIT - 1), "strategy": name,
                         "final": fin, "remaining": rem, "rem_min": float(nv[k:].min() / nv[k - 1] - 1),
                         "base_final": float(nav[-1] / INIT - 1), "top12": int(fin > t12), "top30": int(fin > t30),
                         "turnover": r["turnover"]})
    return pd.DataFrame(rows)


def recov_summary(r: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for st, g in r.groupby("strategy", sort=False):
        rows.append({"strategy": st, "n_events": len(g), "P_final_gt0": (g.final > 0).mean(),
                     "P_beat_base": (g.final > g.base_final + 1e-9).mean(), "P_worse_than_base": (g.final < g.base_final - 1e-9).mean(),
                     "mean_final": g.final.mean(), "median_final": g.final.median(), "mean_remaining": g.remaining.mean(),
                     "p10_final": g.final.quantile(0.1), "worst_final": g.final.min(), "mean_rem_min": g.rem_min.mean(),
                     "top12": g.top12.mean(), "top30": g.top30.mean(), "turnover": g.turnover.mean()})
    return pd.DataFrame(rows)


def carry(row_oos, row_disc, base_oos, placebo_p, viol) -> dict:
    ck = {"a_edge": bool(row_oos.ex_mean >= 0.005 and row_oos.ex_median > 0),
          "b_sig": bool(row_oos.p_holm < 0.10 or row_oos.ci_lo > 0),
          "c_disc": bool(row_disc.ex_mean >= -0.003),
          "d_tail": bool(row_oos.cvar10 >= base_oos.cvar10 - 0.01 and row_oos.worst_window >= base_oos.worst_window - 0.01),
          "e_cost": bool((row_oos.cost - base_oos.cost) / INIT < 0.005),
          "f_placebo": True if placebo_p is None else bool(placebo_p < 0.10), "g_viol": bool(viol == 0)}
    ck["PASS_ALL"] = all(ck.values())
    return ck


def md(df: pd.DataFrame, pct: list[str], fmt: int = 2) -> str:
    d = df.copy()
    for c in d.columns:
        if c in pct:
            d[c] = (d[c] * 100).round(fmt)
        elif d[c].dtype.kind == "f":
            d[c] = d[c].round(4)
    return d.to_markdown(index=False) if hasattr(d, "to_markdown") else d.to_string(index=False)


def main() -> int:
    t0 = time.time()
    data = L.Data()
    wsA = windows("DENSE24")
    variants = S.make_variants(data)
    # ---- A: real pipeline
    fa = family_a(data, wsA, "A")
    fa.to_csv(OUT / "familyA_windows.csv", index=False)
    # ---- B/C/D: replay on the pre-registered windows
    rp = S.run_replays(data, wsA, variants)
    rp.to_csv(OUT / "replay_windows.csv", index=False)
    print("replay done", round(time.time() - t0), flush=True)
    # replay BASE metrics are the daily-NAV convention (no dividend accrual) = family A's A100 (same convention)
    allw = pd.concat([fa.rename(columns={}), rp[rp.variant != "BASE"].assign(variant=lambda x: x.variant)], ignore_index=True)
    # paired statistics: family A vs A100 ; replay variants vs BASE (replay BASE == A100 by gate R0)
    r0 = rp[rp.variant == "BASE"].set_index("start").ret - fa[fa.variant == "A100"].set_index("start").ret
    gate = {"R0_mean_abs_diff_pp": float(r0.abs().mean() * 100), "R0_max_abs_diff_pp": float(r0.abs().max() * 100),
            "R0_pass": bool(r0.abs().mean() * 100 <= 0.05)}
    json.dump(gate, open(OUT / "gate_r0.json", "w"))
    print(gate, flush=True)
    sa = summarize(fa, "A100")
    sr = summarize(rp, "BASE")
    sa.to_csv(OUT / "summary_familyA.csv", index=False)
    sr.to_csv(OUT / "summary_replay.csv", index=False)
    # Holm over every declared variant (A 5 + replay 20) on OOS p
    ps = {r.variant: r.p_signflip for r in pd.concat([sa, sr]).itertuples() if r.sample == "OOS" and r.variant not in ("A100", "BASE")}
    hp = holm(ps)
    # bootstrap CIs
    ci = {}
    for name, d, base in [(v, fa, "A100") for v in fa.variant.unique() if v != "A100"] + [(v, rp, "BASE") for v in rp.variant.unique() if v != "BASE"]:
        g = d[(d.variant == name) & (d.period == "OOS")].sort_values("start").set_index("start")
        b = d[(d.variant == base) & (d.period == "OOS")].sort_values("start").set_index("start")
        ci[name] = block_ci((g.ret - b.ret.loc[g.index]).to_numpy())
    # placebos
    plc = {}
    for nm in ("D1_BREADTH_TREND", "D2_VOL", "D3_SOX", "D4_ANY", "R1_F2a", "R1_F3a", "R1_F9b"):
        dist = placebo(data, wsA, nm, 20)
        g = rp[(rp.variant == nm) & (rp.period == "OOS")].sort_values("start")
        b = rp[(rp.variant == "BASE") & (rp.period == "OOS")].sort_values("start").set_index("start")
        ex = float((g.set_index("start").ret - b.ret.loc[g.start]).iloc[::2].mean())
        plc[nm] = {"actual_oos_ex_subset": ex, "placebo_mean": float(np.mean(dist)), "placebo_p": float((np.array(dist) >= ex).mean())}
        print("placebo", nm, plc[nm], round(time.time() - t0), flush=True)
    json.dump(plc, open(OUT / "placebos.json", "w"), indent=1)
    # carry table
    allsum = pd.concat([sa, sr])
    rows = []
    for v in sorted(set(allsum.variant) - {"A100", "BASE"}):
        o = allsum[(allsum.variant == v) & (allsum["sample"] == "OOS")].iloc[0].copy()
        dd = allsum[(allsum.variant == v) & (allsum["sample"] == "DISCOVERY")].iloc[0]
        bn = "A100" if v.startswith("A") else "BASE"
        bo = allsum[(allsum.variant == bn) & (allsum["sample"] == "OOS")].iloc[0]
        o["p_holm"], o["ci_lo"] = hp.get(v, np.nan), ci[v][0]
        viol = int((fa if v.startswith("A") else rp)[lambda x: x.variant == v].get("viol", pd.Series([0])).sum())
        c = carry(o, dd, bo, plc.get(v, {}).get("placebo_p"), viol)
        rows.append({"variant": v, "oos_ex_mean_pp": o.ex_mean * 100, "oos_ex_median_pp": o.ex_median * 100,
                     "disc_ex_mean_pp": dd.ex_mean * 100, "p_signflip": o.p_signflip, "p_holm": o.p_holm,
                     "ci95_lo_pp": ci[v][0] * 100, "ci95_hi_pp": ci[v][1] * 100, **c})
    ct = pd.DataFrame(rows)
    ct.to_csv(OUT / "carry_table.csv", index=False)
    print(ct.round(3).to_string(), flush=True)
    # ---- recovery (A + B windows; B only sample-size extension)
    wsb = ws_B()
    rec_all = []
    for band, tag in (((-0.05, -0.03), "primary[-5,-3]"), ((-0.06, -0.02), "secondary[-6,-2]")):
        for ws, src in ((wsA, "A"), (wsb, "B")):
            if src == "B" and not (RUNS / f"A5__{wsb[0]['start']}").exists():
                continue
            r = recovery(data, ws, variants, band)
            r["band"], r["src"] = tag, src
            rec_all.append(r)
    rr = pd.concat(rec_all, ignore_index=True)
    rr.to_csv(OUT / "recovery_events.csv", index=False)
    out = []
    for band in rr.band.unique():
        for srcs, lab in ((["A"], "A only (pre-registered windows)"), (["A", "B"], "A+B (sample-size extension)")):
            g = rr[(rr.band == band) & rr.src.isin(srcs)]
            if len(g) == 0:
                continue
            s = recov_summary(g)
            s.insert(0, "sample", lab)
            s.insert(0, "band", band)
            out.append(s)
    rs = pd.concat(out, ignore_index=True)
    rs.to_csv(OUT / "recovery_summary.csv", index=False)
    print(rs.round(3).to_string(), flush=True)
    print("done", round(time.time() - t0), "s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
