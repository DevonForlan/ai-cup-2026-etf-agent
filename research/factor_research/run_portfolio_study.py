"""RESEARCH ONLY. Portfolio backtests of BASE (frozen Quant v1) vs BASE + candidate factor(s) with the FROZEN
simulator (agent.run_sim.simulate). Candidate columns are appended to the feature frame inside worker processes
only (agent.pipeline.cached_features is wrapped in the worker); config/strategy_quant_v1.yaml is read, never
written. Windows: deterministic consecutive non-overlapping 24-trading-day blocks from the first trading day on or
after 2024-07-01; period label by window start (DISCOVERY < 2025-07-01 <= VALIDATION < 2026-02-01 <= HOLDOUT).

  python research\\factor_research\\run_portfolio_study.py --batch single
  python research\\factor_research\\run_portfolio_study.py --batch custom --spec spec.json
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
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
OUT = ROOT / "research" / "factor_research" / "results"
RUNS = ROOT / "runtime" / "factor_bt"
VAL = ROOT / "data" / "research" / "valuation_daily.parquet"
PERIOD_BOUNDS = ("2025-07-01", "2026-02-01")
_PANELS = None


def windows() -> list[dict]:
    from agent.data.loaders import HistoryStore
    days = [d for d in HistoryStore().dates("daily_prices") if d >= "2024-07-01"]
    out = []
    for i in range(0, len(days) - 24 + 1, 24):
        ds = days[i:i + 24]
        per = "DISCOVERY" if ds[0] < PERIOD_BOUNDS[0] else ("VALIDATION" if ds[0] < PERIOD_BOUNDS[1] else "HOLDOUT")
        out.append({"wid": f"R{len(out) + 1:02d}", "start": ds[0], "end": ds[-1], "period": per})
    return out


def _init():
    global _PANELS
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    import agent.pipeline as PL
    from agent.data.loaders import HistoryStore
    from agent.research.factor_lab import build_panels
    _PANELS, _ = build_panels(HistoryStore(), VAL if VAL.exists() else None)
    ref = _PANELS["mom_20"]
    for k in range(10):          # PLACEBO controls: pure noise, fixed seeds -> null distribution of "improvements"
        rng = np.random.default_rng(1000 + k)
        _PANELS[f"placebo_{k}"] = pd.DataFrame(rng.standard_normal(ref.shape), index=ref.index, columns=ref.columns)
    orig = PL.cached_features

    def patched(store, as_of, trade_date, universe, use_cache=True, disk_cache=True):
        res = orig(store, as_of, trade_date, universe, use_cache, disk_cache)
        fs = copy.copy(res[0])
        f = fs.features.copy()
        for name, panel in _PANELS.items():
            col = f"cand_{name}"
            if trade_date in panel.index:
                f[col] = panel.loc[trade_date].reindex(f.index).to_numpy()
        fs.features = f
        return (fs,) + tuple(res[1:])
    PL.cached_features = patched


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
        rec = int(hit.index[0] - i_min) if len(hit) else -1          # -1 = not recovered in window
    var95 = float(np.quantile(r, 0.05)) if len(r) else np.nan
    return {"vol": float(r.std() * np.sqrt(252)), "downside_vol": float(np.sqrt((dn ** 2).mean()) * np.sqrt(252)) if len(dn) else 0.0,
            "worst_1d": float(r.min()), "worst_5d": float((nav / nav.shift(5) - 1).min()), "var95_1d": var95,
            "cvar95_1d": float(r[r <= var95].mean()) if len(r) else np.nan, "recovery_days": rec,
            "sortino": float(r.mean() / (np.sqrt((dn ** 2).mean()) or np.nan) * np.sqrt(252)) if len(dn) else np.nan}


def run_one(job: dict) -> dict:
    from agent.config import load_strategy
    from agent.run_sim import simulate
    cfg = load_strategy("config/strategy_quant_v1.yaml")
    for name, w in (job.get("extra") or {}).items():
        cfg["score_weights"][f"cand_{name}"] = float(w)
    for k, v in (job.get("base_scale") or {}).items():
        cfg["score_weights"][k] = cfg["score_weights"][k] * v
    rid = f"{job['sid']}__{job['wid']}__c{job.get('cost_mult', 1.0)}_s{job.get('slippage', 0.0)}"
    t0 = time.perf_counter()
    try:
        s = simulate(job["start"], days=24, history=ROOT / "data" / "history", cfg=cfg, run_id=rid, out_root=RUNS,
                     quiet=True, light=True, cost_mult=job.get("cost_mult", 1.0), slippage=job.get("slippage", 0.0),
                     strategy_id=job["sid"])
    except SystemExit as e:
        return {**{k: job[k] for k in ("sid", "wid", "period")}, "error": str(e)}
    daily = pd.read_csv(RUNS / rid / "daily.csv", encoding="utf-8-sig")
    turn = daily["turnover"].astype(float)
    hold = daily["holdings"].astype(int)
    row = {k: job[k] for k in ("sid", "wid", "period", "start")}
    row.update(cost_mult=job.get("cost_mult", 1.0), slippage=job.get("slippage", 0.0),
               ret=float(s["total_return"]), mdd=float(s["mdd"]["include_initial_nav_true"]),
               cum_turnover=float(s["cum_turnover"]), first_day_turnover=float(turn.iloc[0]),
               post_day1_turnover=float(turn.iloc[1:].sum()), avg_daily_turnover=float(turn.mean()),
               orders_per_day=float(daily["orders"].astype(int).mean()),
               orders_per_day_after1=float(daily["orders"].astype(int).iloc[1:].mean()),
               cost=float(s["cum_fees"]) + float(s["cum_tax"]), active_share_min=s.get("active_share_min"),
               violations=int(s["warning_count"]), validation_failures=int(s["validation_failures"]),
               fallbacks=int(s["fallback_days"]), avg_holdings=float(hold.mean()),
               runtime=round(time.perf_counter() - t0, 1))
    row.update(risk_metrics(daily))
    row["calmar_window"] = row["ret"] / row["mdd"] if row["mdd"] > 0 else np.nan
    return row


def run_jobs(jobs: list[dict], out_csv: Path, workers: int = 12) -> pd.DataFrame:
    rows = []
    done = set()
    if out_csv.exists():
        old = pd.read_csv(out_csv)
        rows = old.to_dict("records")
        done = {(r["sid"], r["wid"], r["cost_mult"], r["slippage"]) for r in rows}
    jobs = [j for j in jobs if (j["sid"], j["wid"], j.get("cost_mult", 1.0), j.get("slippage", 0.0)) not in done]
    print(f"{len(jobs)} jobs ({len(done)} cached)", flush=True)
    with ProcessPoolExecutor(workers, initializer=_init) as ex:
        futs = [ex.submit(run_one, j) for j in jobs]
        for i, f in enumerate(as_completed(futs)):
            rows.append(f.result())
            if i % 25 == 0:
                pd.DataFrame(rows).to_csv(out_csv, index=False)
                print(i, len(jobs), flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    return df


def single_jobs(signs: dict[str, int], w: float = 0.2) -> list[dict]:
    W = windows()
    jobs = [{"sid": "BASE_V1", "extra": {}, **x} for x in W]
    for name, sg in signs.items():
        jobs += [{"sid": f"F_{name}", "extra": {name: sg * w}, **x} for x in W]
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", choices=["single", "custom"], default="single")
    ap.add_argument("--spec", default=None, help="json list of {sid, extra, cost_mult?, slippage?, base_scale?}")
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "windows.json").write_text(json.dumps(windows(), indent=1), encoding="utf-8")
    if a.batch == "single":
        inc = pd.read_csv(OUT / "ic_incremental.csv")
        signs = inc[inc.period == "DISCOVERY"].set_index("factor")["sign_from_discovery"].astype(int).to_dict()
        signs = {k: v for k, v in signs.items() if k not in ("rev_yoy", "rev_mom")}      # already in BASE
        jobs = single_jobs(signs)
        out = OUT / (a.out or "portfolio_single.csv")
    else:
        spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
        W = windows()
        jobs = [{**s, **x} for s in spec for x in W if (not s.get("periods") or x["period"] in s["periods"])]
        out = OUT / (a.out or "portfolio_custom.csv")
    t = time.time()
    run_jobs(jobs, out, a.workers)
    print("done", round(time.time() - t), "s ->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
