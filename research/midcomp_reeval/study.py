"""RESEARCH ONLY (Issue #14 round 2). Replay engine with state-dependent policies + analysis (PRE_REGISTRATION.md).

Reuses research/tactical_overlay/lab.py (PIT data, caps, round-1 overlays). The frozen yaml is never written.
Usage:  python research\\midcomp_reeval\\study.py --part all
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "tactical_overlay"))
warnings.filterwarnings("ignore")
import lab as L  # noqa: E402
from run_frozen_windows import windows  # noqa: E402

RUNS = ROOT / "runtime" / "midcomp_bt"
OUT = HERE / "results"
INIT, FEE, TAX, THRESH = L.INIT, L.FEE, L.TAX, L.THRESH
CASH_INV = 0.76                      # cash 24 % (< official 25 %)
TOP12, TOP30, NTEAM = 12 / 659, 30 / 659, 659


# ---------------------------------------------------------------- books / pools
def book(freq: int, start: str, data: L.Data) -> dict | None:
    p = RUNS / f"A{freq}__{start}"
    return L.load_run(p) if (p / "daily.csv").exists() else None


def pool_paths(days: list[str], data: L.Data, n_per_k: int = 500, seed: int = 7) -> np.ndarray:
    """Cumulative-return paths (pool x day) of random equal-weight long-only portfolios bought at day-0 VWAP."""
    rng = np.random.default_rng(seed + int(days[0].replace("-", "")) % 1000)
    v0 = data.vwap.loc[days[0]]
    ok = [t for t in data.close.columns if not pd.isna(v0[t]) and data.close.loc[days, t].notna().all()]
    cum = np.stack([(data.close.loc[d, ok] / v0[ok] - 1).to_numpy(dtype=float) for d in days], axis=1)   # name x day
    paths = []
    for k in (10, 20, 30, 50):
        k = min(k, len(ok))
        for _ in range(n_per_k):
            paths.append(cum[rng.choice(len(ok), size=k, replace=False)].mean(axis=0) - FEE)
    return np.array(paths)


# ---------------------------------------------------------------- replay with policies
def _wts(shares: dict, vw, nav_ref: float) -> dict:
    return {t: n * float(vw[t]) / nav_ref for t, n in shares.items()}


def replay2(days: list[str], base: dict, data: L.Data, policy=None, books: dict | None = None, pool=None) -> dict:
    """Like lab.replay (trade at day VWAP, mark at close, official costs). `policy.act(i, d, ctx)` decides the target for
    day i from information <= close of day i-1: None (follow the frozen book exactly), "HOLD" (no trades),
    ("w", weights) (rebalance to weights now, then continue to follow the policy). ctx exposes the own NAV path, the
    frozen / alternative books' weights at day i, and the rank-proxy percentile."""
    cash, sh = INIT, {}
    navs, turn, cost_tot, viol_off, events = [], 0.0, 0.0, 0, []
    for i, d in enumerate(days):
        vw, cl = data.vwap.loc[d], data.close.loc[d]
        sh = {t: n * (1 + data.stock_div.get((d, t), 0.0)) for t, n in sh.items()}
        nav_x = cash + sum(n * float(vw[t]) for t, n in sh.items())
        fsh = base["shares"][i]
        f_nav = sum(n * float(vw[t]) for t, n in fsh.items()) + base["cash"][i]
        base_w = {t: n * float(vw[t]) / f_nav for t, n in fsh.items()}
        ctx = {"i": i, "d": d, "navs": navs, "base_w": base_w, "events": events, "pool": pool, "days": days,
               "alt_w": lambda name, _i=i, _vw=vw: _alt_weights(books, name, _i, _vw)}
        act = None if policy is None else policy.act(i, d, ctx)
        if act is None:
            new = dict(fsh)
        elif isinstance(act, str) and act == "HOLD":
            new = dict(sh)
        else:
            tw = act[1]
            tgt_sh = {t: x * nav_x / float(vw[t]) for t, x in tw.items() if x > 0}
            cur_w = {t: n * float(vw[t]) / nav_x for t, n in sh.items()}
            tgt_w = {t: n * float(vw[t]) / nav_x for t, n in tgt_sh.items()}
            new = dict(sh)
            for t in set(sh) | set(tgt_sh):
                a_, b_ = cur_w.get(t, 0.0), tgt_w.get(t, 0.0)
                if b_ == 0.0:
                    new.pop(t, None)
                elif a_ == 0.0 or abs(b_ - a_) >= THRESH:
                    new[t] = tgt_sh[t]
        buy = sum(max(new.get(t, 0) - sh.get(t, 0), 0) * float(vw[t]) for t in set(sh) | set(new))
        sell = sum(max(sh.get(t, 0) - new.get(t, 0), 0) * float(vw[t]) for t in set(sh) | set(new))
        c = buy * FEE + sell * (FEE + TAX)
        cash += sell - buy - c
        cost_tot += c
        turn += (buy + sell) / nav_x
        sh = {t: n for t, n in new.items() if n > 0}
        nav = cash + sum(n * float(cl[t]) for t, n in sh.items())
        w = {t: n * float(cl[t]) / nav for t, n in sh.items()}
        if sh and (len(sh) < L.MIN_NAMES or len(sh) > 30 or cash / nav >= L.CASH_MAX
                   or any(v > (0.25 if t == L.TSMC else 0.10) for t, v in w.items())):
            viol_off += 1
        navs.append(nav)
    return {"nav": navs, "turnover": turn, "cost": cost_tot, "viol_official": viol_off, "events": events}


def _alt_weights(books, name, i, vw):
    b = (books or {}).get(name)
    if not b or i >= len(b["shares"]):
        return None
    sh = b["shares"][i]
    nav = sum(n * float(vw[t]) for t, n in sh.items()) + b["cash"][i]
    return {t: n * float(vw[t]) / nav for t, n in sh.items()}


def metrics(navs: list[float]) -> dict:
    return L.path_metrics(navs)


# ---------------------------------------------------------------- policies
def cap_cash(w: dict) -> dict:
    inv = min(sum(w.values()), CASH_INV)
    return L.enforce(w, inv)


class Trigger:
    """Fire once when `cond(ctx)` becomes true (evaluated on information up to the previous close); then act forever."""

    def __init__(self, cond, action, start_day: int = 1):
        self.cond, self.action, self.start_day, self.fired_at = cond, action, start_day, None

    def act(self, i, d, ctx):
        if self.fired_at is None and i >= self.start_day and self.cond(ctx):
            self.fired_at = i
            ctx["events"].append(i)
        if self.fired_at is None:
            return None
        return self.action(i, d, ctx, self.fired_at)


def act_cash(i, d, ctx, k):
    return ("w", cap_cash(ctx["base_w"]))


def act_rerank_hold(book_name):
    state = {}

    def f(i, d, ctx, k):
        if "w" not in state:
            w = ctx["alt_w"](book_name)
            state["w"] = L.enforce(w, sum(w.values())) if w else None
            if state["w"] is None:
                return None
            return ("w", state["w"])
        return "HOLD"
    return f


def act_rerank_follow(book_name):
    def f(i, d, ctx, k):
        w = ctx["alt_w"](book_name)
        return ("w", L.enforce(w, sum(w.values()))) if w else None
    return f


def act_conc(i, d, ctx, k):
    return L.overlay_fn("F9b", ctx["data"])(i, d, ctx["base_w"]) and ("w", ctx["_conc"](i, d, ctx["base_w"]))


def dd_cond(thr):
    def c(ctx):
        navs = ctx["navs"]
        if not navs:
            return False
        path = np.array([INIT] + navs)
        return path[-1] / path.max() - 1 <= thr
    return c


def rank_cond(pct):
    def c(ctx):
        i, navs, pool = ctx["i"], ctx["navs"], ctx["pool"]
        if i < 4 or not navs or pool is None:
            return False
        r = navs[-1] / INIT - 1
        return float((pool[:, i - 1] < r).mean()) < pct
    return c


class Regime:
    """Continuous (non-latching) cash overlay: while `cond(d)`, cap invested share at CASH_INV."""

    def __init__(self, cond):
        self.cond = cond

    def act(self, i, d, ctx):
        return ("w", cap_cash(ctx["base_w"])) if self.cond(d) else None


class Round1:
    def __init__(self, fn):
        self.fn = fn

    def act(self, i, d, ctx):
        return ("w", self.fn(i, d, ctx["base_w"]))


def make_variants(data: L.Data) -> dict:
    mk = data.sig["market"]
    vol_p80 = mk["ew_vol20"].rolling(250, min_periods=60).quantile(0.8)
    d1 = lambda d: bool(mk.at[d, "breadth"] < 0.35 and mk.at[d, "ew_trend20"] < 0)  # noqa: E731
    d2 = lambda d: bool(mk.at[d, "ew_vol20"] > vol_p80.at[d]) if not pd.isna(vol_p80.at[d]) else False  # noqa: E731
    d3 = lambda d: bool(mk.at[d, "SOX_20"] < -0.10) if not pd.isna(mk.at[d, "SOX_20"]) else False  # noqa: E731
    conc = L.overlay_fn("F9b", data)

    def act_conc_(i, d, ctx, k):
        return ("w", conc(i, d, ctx["base_w"]))

    v = {}
    for thr in (3, 5, 7):
        v[f"B_CASH_{thr}"] = lambda t=thr: Trigger(dd_cond(-t / 100), act_cash)
        v[f"B_RERANK_{thr}"] = lambda t=thr: Trigger(dd_cond(-t / 100), act_rerank_hold("A1"))
    for pct, nm in ((0.25, "C25"), (0.10, "C10")):
        v[f"{nm}_RERANK"] = lambda p=pct: Trigger(rank_cond(p), act_rerank_hold("A1"))
        v[f"{nm}_CASH"] = lambda p=pct: Trigger(rank_cond(p), act_cash)
        v[f"{nm}_CONC"] = lambda p=pct: Trigger(rank_cond(p), act_conc_)
    v["D1_BREADTH_TREND"] = lambda: Regime(d1)
    v["D2_VOL"] = lambda: Regime(d2)
    v["D3_SOX"] = lambda: Regime(d3)
    v["D4_ANY"] = lambda: Regime(lambda d: d1(d) or d2(d) or d3(d))
    for nm in ("F1b", "F2a", "F3a", "F9b"):
        v[f"R1_{nm}"] = lambda n=nm: Round1(L.overlay_fn(n, data))
    return v


# ---------------------------------------------------------------- study
def run_replays(data: L.Data, ws: list[dict], variants: dict) -> pd.DataFrame:
    rows = []
    for w in ws:
        s = w["start"]
        base = book(100, s, data)
        if base is None:
            continue
        days = base["days"]
        books = {"A1": book(1, s, data), "A5": book(5, s, data)}
        pool = pool_paths(days, data)
        pf = np.sort(pool[:, -1])
        t12, t30 = np.quantile(pool[:, -1], 1 - TOP12), np.quantile(pool[:, -1], 1 - TOP30)
        for name, mkpol in [("BASE", lambda: None)] + list(variants.items()):
            pol = mkpol()
            r = replay2(days, base, data, pol, books, pool)
            m = metrics(r["nav"])
            rows.append({"start": s, "period": w["period"], "variant": name, "ret": m["ret"], "mdd": m["mdd"],
                         "worst_1d": m["worst_1d"], "turnover": r["turnover"], "cost": r["cost"],
                         "viol": r["viol_official"], "fired": (r["events"][0] if r["events"] else -1),
                         "top12": int(m["ret"] > t12), "top30": int(m["ret"] > t30),
                         "pctile": float((pool[:, -1] < m["ret"]).mean())})
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="all")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True, parents=True)
    t0 = time.time()
    data = L.Data()
    print("data", round(time.time() - t0), "s", flush=True)
    ws = windows("DENSE24")
    variants = make_variants(data)
    df = run_replays(data, ws, variants)
    df.to_csv(OUT / "replay_windows.csv", index=False)
    print("replay", len(df), round(time.time() - t0), "s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
