"""RESEARCH ONLY (Issue #14). Frozen Quant v1 fresh-start runs for the horizon study (PRE_REGISTRATION.md §2–§4).

Calls the real frozen pipeline (`agent.run_sim.simulate`, light mode, official costs). Reads
config/strategy_quant_v1.yaml, never writes it. Outputs runtime/tactical_bt/<set>__<start>/ (gitignored) and
research/tactical_overlay/results/frozen_<set>.csv.

  python research\\tactical_overlay\\run_frozen_windows.py --set DENSE24 --workers 12
  python research\\tactical_overlay\\run_frozen_windows.py --set H60
  python research\\tactical_overlay\\run_frozen_windows.py --set H120
"""
from __future__ import annotations

import argparse
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
warnings.filterwarnings("ignore")
RUNS = ROOT / "runtime" / "tactical_bt"
OUT = HERE / "results"
FIRST, LAST = "2024-07-01", "2026-10-22"
SETS = {"DENSE24": (24, 6), "H60": (60, 24), "H120": (120, 24), "NOV23_24": (24, 24)}
OOS_FROM = "2025-07-01"


def trading_days() -> list[str]:
    from agent.data.loaders import HistoryStore
    return [d for d in HistoryStore(ROOT / "data" / "history").dates("daily_prices") if FIRST <= d <= LAST]


def windows(name: str) -> list[dict]:
    days, (n, step) = trading_days(), SETS[name]
    out = []
    for i in range(0, len(days) - n + 1, step):
        out.append({"set": name, "start": days[i], "end": days[i + n - 1], "days": n,
                    "period": "DISCOVERY" if days[i] < OOS_FROM else "OOS"})
    return out


def run_one(w: dict) -> dict:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    from agent.config import load_strategy
    from agent.run_sim import simulate
    rid = f"{w['set']}__{w['start']}"
    t0 = time.perf_counter()
    try:
        s = simulate(w["start"], days=w["days"], history=ROOT / "data" / "history",
                     cfg=load_strategy("config/strategy_quant_v1.yaml"), run_id=rid, out_root=RUNS, quiet=True,
                     light=True, strategy_id="FROZEN_V1")
    except (SystemExit, OSError) as e:          # OSError: Windows rename race on the shared feature cache
        return {**w, "error": f"{type(e).__name__}: {str(e)[:160]}"}
    d = pd.read_csv(RUNS / rid / "daily.csv", encoding="utf-8-sig")
    return {**w, "run_id": rid, "ret": float(s["total_return"]), "mdd": float(s["mdd"]["include_initial_nav_true"]),
            "turnover": float(d["turnover"].astype(float).sum()), "turnover_post_day1": float(d["turnover"].astype(float).iloc[1:].sum()),
            "cost": float(s["cum_fees"]) + float(s["cum_tax"]), "avg_cash": float(d["cash_ratio"].astype(float).mean()),
            "violations": int(s["warning_count"]), "validation_failures": int(s["validation_failures"]),
            "fallbacks": int(s["fallback_days"]), "n_days": int(len(d)), "runtime": round(time.perf_counter() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=list(SETS), required=True)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"frozen_{a.set}.csv"
    ws = windows(a.set)
    prev = pd.read_csv(out) if out.exists() else pd.DataFrame()
    if len(prev) and "error" in prev:
        prev = prev[prev["error"].isna()]           # retry failed windows
    done = set(prev["start"]) if len(prev) else set()
    rows = prev.to_dict("records") if len(prev) else []
    todo = [w for w in ws if w["start"] not in done]
    print(f"{a.set}: {len(ws)} windows, {len(todo)} to run", flush=True)
    t = time.time()
    with ProcessPoolExecutor(a.workers) as ex:
        for i, f in enumerate(as_completed([ex.submit(run_one, w) for w in todo])):
            rows.append(f.result())
            if i % 10 == 0:
                pd.DataFrame(rows).sort_values("start").to_csv(out, index=False)
                print(i, len(todo), round(time.time() - t), flush=True)
    pd.DataFrame(rows).sort_values("start").to_csv(out, index=False)
    print("done", round(time.time() - t), "s ->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
