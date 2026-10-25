"""RESEARCH ONLY (Issue #14). Overlay replays vs frozen Quant v1 (PRE_REGISTRATION.md §5–§6).

For each window (NOV23 cached frozen runs; DENSE24 runs from run_frozen_windows.py) the frozen book is replayed
(R0-validated) and every pre-registered overlay variant is applied on top. Placebos for G4 on NOV23-OOS.
Outputs results/overlay_windows.csv, results/overlay_placebo.csv, results/benchmarks.csv.
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import lab as L  # noqa: E402

MAIN_RUNS = Path(r"C:/Users/devon.tseng/Desktop/個人/AI CUP 2026玉山人工智慧公開挑戰賽/runtime/overlay_bt")
OWN_RUNS = L.ROOT / "runtime" / "tactical_bt"
OUT = HERE / "results"
N_PLACEBO = 50
_D = {}


def window_list() -> list[dict]:
    nov = json.loads((L.ROOT / "research" / "factor_research" / "results" / "windows.json").read_text(encoding="utf-8"))
    ws = [{"set": "NOV23", "wid": w["wid"], "start": w["start"], "period": "DISCOVERY" if w["period"] == "DISCOVERY" else "OOS",
           "sub": w["period"], "dir": str(MAIN_RUNS / f"BASE_V1__{w['wid']}__c1.0_s0.0")} for w in nov]
    d24 = pd.read_csv(OUT / "frozen_DENSE24.csv")
    if "error" in d24:
        d24 = d24[d24["error"].isna()]
    ws += [{"set": "DENSE24", "wid": r.run_id, "start": r.start, "period": r.period, "sub": r.period,
            "dir": str(OWN_RUNS / r.run_id)} for r in d24.itertuples()]
    return ws


def _init():
    _D["data"] = L.Data()


def one_window(w: dict) -> list[dict]:
    data = _D["data"]
    run = L.load_run(Path(w["dir"]))
    days = run["days"]
    base = L.replay(days, run, data)
    bm = L.path_metrics(base["nav"])
    rp_x = L.random_portfolios(days, data, exit_cost=True)
    rp_n = L.random_portfolios(days, data, exit_cost=False)
    ew = L.ew_universe(days, data)
    rows = []

    def row(variant, res):
        m = L.path_metrics(res["nav"])
        return {**{k: w[k] for k in ("set", "wid", "start", "period", "sub")}, "variant": variant, **m,
                "turnover": res["turnover"], "cost_pct": res["cost"] / L.INIT, "violations": res["violations"], "violations_official": res["violations_official"],
                "d_ret": m["ret"] - bm["ret"], "d_mdd": m["mdd"] - bm["mdd"], "ew_ret": ew,
                "pctile_exitcost": L.percentile(m["ret"], rp_x), "pctile_nav": L.percentile(m["ret"], rp_n)}
    rows.append(row("BASE", base))
    for v in L.VARIANTS:
        rows.append(row(v, L.replay(days, run, data, L.overlay_fn(v, data))))
    return rows


def placebo_window(args) -> list[dict]:
    w, v = args
    data = _D["data"]
    run = L.load_run(Path(w["dir"]))
    days = run["days"]
    b = L.path_metrics(L.replay(days, run, data)["nav"])["ret"]
    out = []
    for k in range(N_PLACEBO):
        if v in L.NAME_PLACEBO:
            fn = L.overlay_fn(v, data, rng=np.random.default_rng(1000 + k))
        else:
            fn = L.overlay_fn(v, data, shift=int(np.random.default_rng(2000 + k).integers(20, len(data.dates) - 20)))
        r = L.path_metrics(L.replay(days, run, data, fn)["nav"])["ret"]
        out.append({"wid": w["wid"], "variant": v, "k": k, "d_ret": r - b})
    return out


def main() -> int:
    OUT.mkdir(exist_ok=True)
    ws = window_list()
    t = time.time()
    with ProcessPoolExecutor(12, initializer=_init) as ex:
        rows = [r for part in ex.map(one_window, ws, chunksize=2) for r in part]
    pd.DataFrame(rows).to_csv(OUT / "overlay_windows.csv", index=False)
    print("overlay windows", len(ws), round(time.time() - t), "s", flush=True)
    oos = [w for w in ws if w["set"] == "NOV23" and w["period"] == "OOS"]
    jobs = [(w, v) for v in L.VARIANTS for w in oos]
    with ProcessPoolExecutor(12, initializer=_init) as ex:
        pl = [r for part in ex.map(placebo_window, jobs, chunksize=4) for r in part]
    pd.DataFrame(pl).to_csv(OUT / "overlay_placebo.csv", index=False)
    print("placebo", len(pl), round(time.time() - t), "s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
