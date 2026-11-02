"""RESEARCH ONLY (Issue #14 round 2, PRE_REGISTRATION §2A). Real frozen pipeline with only turnover.rebalance_every changed
in an in-memory config copy (the yaml is never written). Outputs runtime/midcomp_bt/<A..>__<start>/ (gitignored) and
research/midcomp_reeval/results/rebalance_<A>.csv.   python research\midcomp_reeval\run_rebalance.py --freq 20 --workers 14"""
from __future__ import annotations

import argparse
import copy
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "tactical_overlay"))
warnings.filterwarnings("ignore")
RUNS = ROOT / "runtime" / "midcomp_bt"
OUT = HERE / "results"


def run_one(args: tuple) -> dict:
    w, freq = args
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    from agent.config import load_strategy
    from agent.run_sim import simulate
    cfg = copy.deepcopy(load_strategy("config/strategy_quant_v1.yaml"))
    cfg["turnover"]["rebalance_every"] = freq
    rid = f"A{freq}__{w['start']}"
    t0 = time.perf_counter()
    try:
        s = simulate(w["start"], days=w["days"], history=ROOT / "data" / "history", cfg=cfg, run_id=rid, out_root=RUNS,
                     quiet=True, light=True, strategy_id=f"A{freq}")
    except (SystemExit, OSError) as e:
        return {**w, "freq": freq, "error": f"{type(e).__name__}: {str(e)[:160]}"}
    d = pd.read_csv(RUNS / rid / "daily.csv", encoding="utf-8-sig")
    return {**w, "freq": freq, "run_id": rid, "ret": float(s["total_return"]), "mdd": float(s["mdd"]["include_initial_nav_true"]),
            "turnover": float(d["turnover"].astype(float).sum()), "cost": float(s["cum_fees"]) + float(s["cum_tax"]),
            "avg_cash": float(d["cash_ratio"].astype(float).mean()), "violations": int(s["warning_count"]),
            "validation_failures": int(s["validation_failures"]), "n_days": int(len(d)), "runtime": round(time.perf_counter() - t0, 1)}


def main() -> int:
    from run_frozen_windows import windows
    ap = argparse.ArgumentParser()
    ap.add_argument("--freq", type=int, required=True)
    ap.add_argument("--workers", type=int, default=14)
    ap.add_argument("--set", default="A", choices=["A", "B", "ACTUAL"])   # A = pre-registered 90 windows; B = shifted-by-3 extension (sample size only); ACTUAL = 10/27 start, descriptive
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / (f"rebalance_A{a.freq}.csv" if a.set == "A" else f"rebalance_{a.set}_A{a.freq}.csv")
    ws = windows("DENSE24")
    if a.set == "B":
        from run_frozen_windows import trading_days
        days = trading_days()
        ws = [{"set": "B", "start": days[i], "end": days[i + 23], "days": 24, "period": "DISCOVERY" if days[i] < "2025-07-01" else "OOS"}
              for i in range(3, len(days) - 23, 6)]
    elif a.set == "ACTUAL":
        ws = [{"set": "ACTUAL", "start": "2026-10-27", "end": "2026-11-02", "days": 5, "period": "ACTUAL"}]
    prev = pd.read_csv(out) if out.exists() else pd.DataFrame()
    if len(prev) and "error" in prev:
        prev = prev[prev["error"].isna()]
    done = set(prev["start"]) if len(prev) else set()
    rows = prev.to_dict("records") if len(prev) else []
    todo = [w for w in ws if w["start"] not in done]
    print(f"A{a.freq}: {len(ws)} windows, {len(todo)} to run", flush=True)
    t = time.time()
    with ProcessPoolExecutor(a.workers) as ex:
        for i, f in enumerate(as_completed([ex.submit(run_one, (w, a.freq)) for w in todo])):
            rows.append(f.result())
            if i % 10 == 0:
                pd.DataFrame(rows).sort_values("start").to_csv(out, index=False)
                print(i, len(todo), round(time.time() - t), flush=True)
    pd.DataFrame(rows).sort_values("start").to_csv(out, index=False)
    print("done", round(time.time() - t), "s ->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
