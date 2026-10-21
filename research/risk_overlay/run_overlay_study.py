"""RESEARCH ONLY. Risk Overlay backtests: frozen Quant v1 (selection unchanged) + exposure overlay.

The overlay is injected only inside worker processes by wrapping `agent.pipeline.construct`: on overlay days a
Crash-Guard-style dict is passed so the EXISTING `_guard_scale` scales current holdings (no name changes). On
NORMAL days no guard is passed (identical to v1) except a capped re-leveraging back to v1's cash range after an
overlay episode. config/strategy_quant_v1.yaml is read, never written. Windows = research/factor_research/results/
windows.json (same 23 windows as the Factor round).

  python research\\risk_overlay\\run_overlay_study.py --batch main
  python research\\risk_overlay\\run_overlay_study.py --batch placebo --cands A_FAST,C_VOTE --n 20
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
warnings.filterwarnings("ignore")
import overlay_lab as L  # noqa: E402

OUT = HERE / "results"
RUNS = ROOT / "runtime" / "overlay_bt"
WINDOWS = json.loads((ROOT / "research" / "factor_research" / "results" / "windows.json").read_text(encoding="utf-8"))
_ST = {"states": None, "job": None, "date": None, "fs": None, "engaged": False}


def all_states() -> pd.DataFrame:
    from agent.data.loaders import HistoryStore
    return L.candidate_states(L.build_signals(HistoryStore()))


def placebo_offsets(n: int, length: int, seed: int = 11) -> list[int]:
    rng = np.random.default_rng(seed)
    return [int(x) for x in rng.integers(20, length - 20, size=n)]


def job_series(job: dict, S: pd.DataFrame) -> pd.Series:
    s = S[L.CANDIDATES[job["cand"]][1]] if job.get("cand") else pd.Series("NORMAL", index=S.index)
    return L.shifted(s, job["offset"]) if job.get("offset") else s


def _init():
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    import agent.pipeline as PL
    from agent.config import D
    from agent.portfolio import baseline as B
    _ST["states"] = all_states()
    orig_cf, orig_construct = PL.cached_features, PL.construct

    def cf(store, as_of, trade_date, universe, use_cache=True, disk_cache=True):
        res = orig_cf(store, as_of, trade_date, universe, use_cache, disk_cache)
        if as_of.endswith("T07:00:00+08:00") and _ST["job"] is not None:
            _ST["date"], _ST["fs"] = trade_date, res[0]
        return res

    def construct(*args):
        job = _ST["job"]
        args = list(args)
        if job is None or not job.get("cand"):
            return orig_construct(*args)
        scores, prev_h, prev_cash, nav_prev, closes_prev, rb, cfg, market = args[:8]
        d = _ST["date"]
        if d == job["start"]:
            _ST["engaged"] = False
        st = job["_series"].get(d, "NORMAL")
        held = {t: int(s) for t, s in prev_h.items() if int(s) > 0}
        nav_prev = D(nav_prev)
        inv = sum((Decimal(s) * D(closes_prev[t]) for t, s in held.items()), Decimal(0)) / nav_prev if held else Decimal(0)
        cash_now = float(1 - inv)
        reg, _, rng, _ = B.regime_from_market(market, cfg)
        v1_lo = max(rng[0], float(cfg["strategy_buffers"]["cash_target_min"])) if reg != "risk_on" else rng[0]
        v1_hi = min(rng[1], 0.20)
        act = L.ACTIONS[L.CANDIDATES[job["cand"]][0]]
        base = {"points": -1, "max_delever": act["max_delever"], "max_relever": 0.10, "cash_hard_ceiling": 0.20,
                "high_vol_quantile": 0.80, "raw_state": st, "calm_days": 0, "detail": {}, "port_dd": 0.0}
        if st == "NORMAL":
            if held and _ST["engaged"] and cash_now > v1_hi + 0.02:
                guard = {**base, "state": "NORMAL", "cash": [v1_lo, v1_hi], "allow_new": True, "vol_cap": None}
            else:
                _ST["engaged"] = False
                return orig_construct(*args)
        else:
            spec = act[st]
            if spec["cash"]:                           # overlay only ADDS cash: never below v1's own range today
                cash = [max(spec["cash"][0], v1_lo), min(max(spec["cash"][1], v1_hi), 0.19)]
            else:
                cash = [0.0, v1_hi] if held else [v1_lo, v1_hi]                   # B: never de-levers
            guard = {**base, "state": st, "cash": list(cash), "allow_new": spec["allow_new"], "vol_cap": spec["vol_cap"]}
            _ST["engaged"] = True
        vol = _ST["fs"].features["volatility_20d"].dropna()
        guard["high_vol"] = sorted(vol[vol >= vol.quantile(0.80)].index) if len(vol) else []
        if not held:                                   # day 1: full construction with the overlay cash range
            while len(args) < 15:
                args.append(None)
            args[14] = guard
            return orig_construct(*args)
        res = overlay_scale(args, held, nav_prev, guard)
        if res is not None:
            return res
        args = args[:13] + [None, None] if len(args) >= 13 else args
        return orig_construct(*args)                  # nothing to do today -> v1 hold logic

    def overlay_scale(args, held, nav_prev, guard):
        """Move cash toward the guard range by trading at most max_(de|re)lever NAV, CONCENTRATED on the largest
        holdings so that each order is >= ~0.25% NAV (the frozen planner ignores per-name changes < 0.2%)."""
        import agent.portfolio.constructor as C
        scores, prev_h, prev_cash, _, closes_prev, rb, cfg, market = args[:8]
        etf_h, etf_meta = args[8], args[9]
        lot = rb.rules.lot_size
        cur_w = {t: Decimal(s) * D(closes_prev[t]) / nav_prev for t, s in held.items()}
        inv = sum(cur_w.values(), Decimal(0))
        cash_now = 1 - inv
        lo, hi = D(str(guard["cash"][0])), D(str(guard["cash"][1]))
        mid = (lo + hi) / 2
        ceiling = D(str(guard["cash_hard_ceiling"]))
        target = dict(cur_w)
        vcap = D(str(guard["vol_cap"])) if guard.get("vol_cap") else None
        trimmed = Decimal(0)
        if vcap is not None and cash_now <= ceiling:
            for t in guard["high_vol"]:
                if t in target and target[t] > vcap + D("0.002"):
                    trimmed += target[t] - vcap
                    target[t] = vcap
        locked = {t for t, s in held.items() if s % lot != 0}
        if cash_now > ceiling or (guard["state"] == "NORMAL" and cash_now > hi + D("0.02")):
            amt = min((1 - mid) - inv, D(str(guard["max_relever"])))          # buy back
            if cash_now > ceiling:
                amt = max(amt, cash_now - (ceiling - D("0.02")))
            sign = 1
        elif cash_now + trimmed < lo - D("0.005"):
            amt = min(inv - trimmed - (1 - mid), D(str(guard["max_delever"])) - trimmed)
            sign = -1
        else:
            amt, sign = Decimal(0), 0
        caps = C._caps(held, rb, cfg)
        if amt > D("0.0025") and sign:
            names = sorted((t for t in target if t not in locked and (sign < 0 or target[t] < caps[t] - D("0.003"))),
                           key=lambda t: -target[t])
            n = max(1, min(len(names), int(amt / D("0.0025"))))
            top = names[:n]
            tot = sum((target[t] for t in top), Decimal(0))
            for t in top:
                target[t] = target[t] + sign * amt * target[t] / tot
                target[t] = min(target[t], caps[t])
        if all(abs(target[t] - cur_w[t]) < D("0.002") for t in target):
            return None
        target = {t: max(Decimal(0), w).quantize(C.Q, rounding="ROUND_FLOOR") for t, w in target.items()}
        no_trade = set(locked) | {t for t in target if abs(target[t] - cur_w[t]) < D("0.002")}
        why = f"Risk Overlay {guard['state']}（研究）"
        info = {"kept": list(held), "new": [], "dropped": [], "rank_of": {}, "guard_scale": True}
        notes = [f"Risk Overlay {guard['state']}：{'回補' if sign > 0 else '降曝險'} {float(amt + trimmed):.2%} NAV"]
        reg = "risk_off" if guard["state"] != "NORMAL" else "neutral"
        return C._finalize(target, no_trade, held, D(prev_cash), nav_prev, closes_prev, rb, cfg, etf_h, etf_meta,
                           reg, "defensive" if reg == "risk_off" else "neutral", why,
                           (float(lo), float(hi)), info, notes)

    PL.cached_features = cf
    PL.construct = construct


def risk_metrics(daily: pd.DataFrame, init: float = 1e9) -> dict:
    nav = pd.concat([pd.Series([init]), daily["nav"].astype(float)], ignore_index=True)
    r = nav.pct_change().dropna()
    dn = r[r < 0]
    peak = nav.cummax()
    dd = nav / peak - 1
    rec = 0
    if dd.min() < 0:
        i_min = int(dd.idxmin())
        after = nav.iloc[i_min:]
        hit = after[after >= peak.iloc[i_min]]
        rec = int(hit.index[0] - i_min) if len(hit) else -1
    var95 = float(np.quantile(r, 0.05))
    return {"downside_vol": float(np.sqrt((dn ** 2).mean()) * np.sqrt(252)) if len(dn) else 0.0,
            "worst_1d": float(r.min()), "worst_5d": float((nav / nav.shift(5) - 1).min()),
            "cvar95_1d": float(r[r <= var95].mean()), "recovery_days": rec,
            "sortino": float(r.mean() / np.sqrt((dn ** 2).mean()) * np.sqrt(252)) if len(dn) else np.nan}


def run_one(job: dict) -> dict:
    from agent.config import load_strategy
    from agent.run_sim import simulate
    cfg = load_strategy("config/strategy_quant_v1.yaml")
    S = _ST["states"]
    series = job_series(job, S)
    win_days = [d for d in S.index if job["start"] <= d <= job["end"]]
    active = int((series.reindex(win_days) != "NORMAL").sum())
    row = {k: job.get(k) for k in ("sid", "cand", "offset", "wid", "period", "start")}
    row.update(cost_mult=job.get("cost_mult", 1.0), slippage=job.get("slippage", 0.0), overlay_days=active)
    if job.get("cand") and active == 0:
        row["identical_to_base"] = True              # overlay never on in this window -> result == BASE (no run)
        return row
    job = {**job, "_series": series.to_dict()}
    _ST["job"], _ST["engaged"] = job, False
    rid = f"{job['sid']}__{job['wid']}__c{row['cost_mult']}_s{row['slippage']}"
    t0 = time.perf_counter()
    try:
        s = simulate(job["start"], days=24, history=ROOT / "data" / "history", cfg=cfg, run_id=rid, out_root=RUNS,
                     quiet=True, light=True, cost_mult=row["cost_mult"], slippage=row["slippage"], strategy_id=job["sid"])
    except SystemExit as e:
        return {**row, "error": str(e)}
    finally:
        _ST["job"] = None
    daily = pd.read_csv(RUNS / rid / "daily.csv", encoding="utf-8-sig")
    turn = daily["turnover"].astype(float)
    row.update(identical_to_base=False, ret=float(s["total_return"]), mdd=float(s["mdd"]["include_initial_nav_true"]),
               first_day_turnover=float(turn.iloc[0]), post_day1_turnover=float(turn.iloc[1:].sum()),
               cost=float(s["cum_fees"]) + float(s["cum_tax"]),
               active_share_min=pd.to_numeric(daily["active_share_min"], errors="coerce").min(),
               max_cash=float(daily["cash_ratio"].astype(float).max()), avg_cash=float(daily["cash_ratio"].astype(float).mean()),
               violations=int(s["warning_count"]), validation_failures=int(s["validation_failures"]),
               fallbacks=int(s["fallback_days"]), runtime=round(time.perf_counter() - t0, 1))
    row.update(risk_metrics(daily))
    return row


def run_jobs(jobs: list[dict], out_csv: Path, workers: int = 10) -> pd.DataFrame:
    rows, done = [], set()
    key = lambda r: (r["sid"], r["wid"], float(r.get("cost_mult", 1.0)), float(r.get("slippage", 0.0)))  # noqa: E731
    if out_csv.exists():
        rows = pd.read_csv(out_csv).to_dict("records")
        done = {key(r) for r in rows}
    jobs = [j for j in jobs if key(j) not in done]
    print(f"{len(jobs)} jobs ({len(done)} cached)", flush=True)
    if jobs:
        with ProcessPoolExecutor(workers, initializer=_init) as ex:
            futs = [ex.submit(run_one, j) for j in jobs]
            for i, f in enumerate(as_completed(futs)):
                rows.append(f.result())
                if i % 20 == 0:
                    pd.DataFrame(rows).to_csv(out_csv, index=False)
                    print(i, len(jobs), flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", choices=["main", "stress", "placebo", "probe"], default="main")
    ap.add_argument("--cands", default=",".join(L.CANDIDATES))
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--workers", type=int, default=10)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cands = [c for c in a.cands.split(",") if c]
    oos = [w for w in WINDOWS if w["period"] != "DISCOVERY"]
    if a.batch == "probe":
        jobs = [{"sid": "BASE_V1", "cand": None, **WINDOWS[7]}, {"sid": "A_VOTE", "cand": "A_VOTE", **WINDOWS[7]}]
        out = OUT / "probe.csv"
    elif a.batch == "main":
        jobs = [{"sid": "BASE_V1", "cand": None, **w} for w in WINDOWS]
        jobs += [{"sid": c, "cand": c, **w} for c in cands for w in WINDOWS]
        out = OUT / "overlay_main.csv"
    elif a.batch == "stress":
        jobs = [{"sid": c or "BASE_V1", "cand": c, "cost_mult": cm, "slippage": sl, **w}
                for c in [None] + cands for w in oos for cm, sl in ((1.5, 0.0), (1.0, 0.002))]
        out = OUT / "overlay_stress.csv"
    else:
        S = all_states()
        offs = placebo_offsets(a.n, len(S))
        (OUT / "placebo_offsets.json").write_text(json.dumps(offs), encoding="utf-8")
        jobs = [{"sid": f"PL_{c}_{k:02d}", "cand": c, "offset": o, **w} for c in cands for k, o in enumerate(offs) for w in oos]
        out = OUT / "overlay_placebo.csv"
    t = time.time()
    run_jobs(jobs, out, a.workers)
    print("done", round(time.time() - t), "s ->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
