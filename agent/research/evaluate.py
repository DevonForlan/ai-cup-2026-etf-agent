"""Round 03 research harness: strategies × windows (24 trading days each), run in parallel.

  python agent\\research\\evaluate.py --batch main            # all registry strategies × windows
  python agent\\research\\evaluate.py --batch main --only A9_full,A10_full_ctrl
  python agent\\research\\evaluate.py --random-only           # Monte Carlo random baselines

Outputs (reports/):
  strategy_leaderboard.csv     one row per strategy × window (+ cost/slippage stress rows)
  random_baseline.csv          percentiles of 1000 random 25-stock portfolios per window
  windows.json                 actual dates used per window
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT, load_strategy, load_universe  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.research.strategies import config_hash, registry, resolve  # noqa: E402
from agent.sim.calendar import TradingCalendar  # noqa: E402

REPORTS = ROOT / "reports"
WINDOW_DAYS = 24
_STORE: HistoryStore | None = None


def _init_worker(history: str):
    global _STORE
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    _STORE = HistoryStore(history)


def closes_panel(store: HistoryStore) -> pd.DataFrame:
    p = store.load("daily_prices")
    return p.pivot(index="date", columns="ticker", values="close").sort_index().astype(float)


# ------------------------------------------------------------------ windows
def window_days(cal: TradingCalendar, start: str, n: int = WINDOW_DAYS) -> list[str]:
    return [d for d in cal.days if d >= start][:n]


def pick_windows(store: HistoryStore, fixed: dict[str, str], min_lookback: int = 65) -> dict:
    """W1/W2/W5 from the plan (start dates); W3 = strongest, W4 = flattest 24-day EW-universe
    window among remaining non-overlapping candidates (with >= min_lookback days of history)."""
    cal = TradingCalendar(store.dates("daily_prices"))
    c = closes_panel(store)
    ew = c.pct_change(fill_method=None).median(axis=1)
    out = {}
    used: set[str] = set()
    for wid, start in fixed.items():
        ds = window_days(cal, start)
        out[wid] = {"start": ds[0], "end": ds[-1], "days": len(ds), "kind": "planned"}
        used |= set(ds)
    days = cal.days
    cand = []
    for i in range(min_lookback, len(days) - WINDOW_DAYS + 1, 5):
        ds = days[i:i + WINDOW_DAYS]
        if used & set(ds):
            continue
        r = float(c.loc[ds[-1]].div(c.loc[days[i - 1]]).sub(1).mean())   # EW buy&hold, same as reported
        v = float(ew.loc[ds].std() * np.sqrt(252))
        cand.append((ds, r, v))
    best = max(cand, key=lambda x: x[1])
    out["W3"] = {"start": best[0][0], "end": best[0][-1], "days": WINDOW_DAYS, "kind": "strong_bull",
                 "ew_ret": best[1], "ew_vol": best[2]}
    rest = [x for x in cand if not set(x[0]) & set(best[0])]
    flat = min(rest, key=lambda x: abs(x[1]) + 0.5 * x[2])
    out["W4"] = {"start": flat[0][0], "end": flat[0][-1], "days": WINDOW_DAYS, "kind": "range_bound",
                 "ew_ret": flat[1], "ew_vol": flat[2]}
    for wid, w in out.items():
        ds = window_days(cal, w["start"])
        prev = cal.prev(ds[0])
        w["ew_ret"] = float(c.loc[ds[-1]].div(c.loc[prev]).sub(1).mean())
        w["ew_vol"] = float(ew.loc[ds].std() * np.sqrt(252))
    return dict(sorted(out.items()))


# ------------------------------------------------------------------ random baseline
def random_mc(store: HistoryStore, days: list[str], n: int = 1000, k: int = 25, cash: float = 0.05,
              seed: int = 7, init: float = 1e9) -> np.ndarray:
    """n random legal 25-stock equal-weight portfolios bought at day-1 VWAP (official fees), held to
    the last close; accrued cash dividends added. Returns total returns."""
    cal = TradingCalendar(store.dates("daily_prices"))
    p = store.load("daily_prices")
    prev = cal.prev(days[0])
    sub = p[p["date"].isin([prev, days[0], days[-1]])]
    close_prev = sub[sub.date == prev].set_index("ticker")["close"].astype(float)
    d0 = sub[sub.date == days[0]].set_index("ticker")
    vwap0 = (d0["amount"].astype(float) / d0["volume"].astype(float)).replace([np.inf], np.nan)
    close_end = sub[sub.date == days[-1]].set_index("ticker")["close"].astype(float)
    tick = sorted(set(close_prev.dropna().index) & set(vwap0.dropna().index) & set(close_end.dropna().index))
    cp, vw, ce = (close_prev.reindex(tick).to_numpy(), vwap0.reindex(tick).to_numpy(), close_end.reindex(tick).to_numpy())
    ca = store.load("corporate_actions")
    div = np.zeros(len(tick))
    if len(ca):
        ca = ca[ca["ex_date"].isin(days[1:]) & ca["ticker"].isin(tick)]
        dmap = ca.groupby("ticker")["cash_dividend"].sum().to_dict()
        div = np.array([dmap.get(t, 0.0) for t in tick])
    rng = np.random.default_rng(seed)
    idx = np.argsort(rng.random((n, len(tick))), axis=1)[:, :k]
    w = (1 - cash) / k
    shares = np.floor(w * init / cp[idx] / 1000) * 1000
    cost = shares * vw[idx]
    cash_end = init - (cost * (1 + 0.001425)).sum(axis=1)
    nav = (shares * ce[idx]).sum(axis=1) + cash_end + (shares * div[idx]).sum(axis=1)
    return nav / init - 1


def buy_hold_refs(store: HistoryStore, days: list[str]) -> dict:
    """Reference (not necessarily legal) buy-and-hold returns, close(T-1) -> close(end)."""
    cal = TradingCalendar(store.dates("daily_prices"))
    c = closes_panel(store)
    prev = cal.prev(days[0])
    r = (c.loc[days[-1]] / c.loc[prev] - 1).dropna()
    uni = pd.read_csv(ROOT / "config" / "universe_150.csv", dtype=str, encoding="utf-8-sig")
    tw = uni[uni.market == "TWSE"]["ticker"].tolist()
    # official list order is column-major per page (left column = higher market cap); left col rows 0,2,4..
    top25 = [tw[i] for i in range(0, 60, 2)][:25]
    return {"ew150": float(r.mean()), "top25_mcap_ew": float(r.reindex(top25).dropna().mean()),
            "tsmc_2330": float(r.get("2330", np.nan))}


# ------------------------------------------------------------------ IC / hit rate
def ic_hit(scores: dict, decisions: dict, closes: pd.DataFrame, cal: TradingCalendar) -> dict:
    ic1, ic5, hits = [], [], []
    for d, sc in scores.items():
        prev = cal.prev(d)
        i = cal.days.index(d)
        if prev not in closes.index or d not in closes.index:
            continue
        s = sc.loc[sc["eligible"].astype(bool), "raw_score"].dropna()
        r1 = (closes.loc[d] / closes.loc[prev] - 1).reindex(s.index)
        m = r1.notna()
        if m.sum() > 20:
            ic1.append(s[m].rank().corr(r1[m].rank()))
        if i + 4 < len(cal.days) and cal.days[i + 4] in closes.index:
            r5 = (closes.loc[cal.days[i + 4]] / closes.loc[prev] - 1)
            rs = r5.reindex(s.index)
            m5 = rs.notna()
            if m5.sum() > 20:
                ic5.append(s[m5].rank().corr(rs[m5].rank()))
            med = r5.median()
            for t, a in decisions.get(d, []):
                if a in ("BUY", "ADD") and pd.notna(r5.get(t)):
                    hits.append(float(r5[t] > med))
    f = lambda x: float(np.nanmean(x)) if x else None  # noqa: E731
    return {"rank_ic_1d": f(ic1), "rank_ic_5d": f(ic5), "hit_rate_5d": f(hits), "n_hits": len(hits)}


# ------------------------------------------------------------------ one job
def run_job(job: dict) -> dict:
    from agent.run_sim import simulate
    store = _STORE
    cfg = job["cfg"]
    w = job["window"]
    t0 = time.perf_counter()
    try:
        s = simulate(w["start"], history=store.root, cfg=cfg, days=WINDOW_DAYS, run_id=job["run_id"],
                     out_root=Path(job["out_root"]), quiet=True, light=True, keep_scores=True,
                     cost_mult=job.get("cost_mult", 1.0), slippage=job.get("slippage", 0.0), store=store,
                     strategy_id=job["strategy_id"], data_faults=set(job.get("faults", [])) or None)
    except Exception as e:  # noqa: BLE001
        import traceback
        return {"strategy_id": job["strategy_id"], "window": job["wid"], "error": f"{e}\n{traceback.format_exc()[-1500:]}"}
    cal = TradingCalendar(store.dates("daily_prices"))
    closes = closes_panel(store)
    ich = ic_hit(s.pop("_scores"), s.pop("_decisions"), closes, cal)
    daily = s.pop("_daily")
    row = {
        "strategy_id": job["strategy_id"], "group": job["group"], "window": job["wid"],
        "start": s["start"], "end": s["end"], "days": s["days"], "variant": job.get("variant", "official"),
        "return": float(s["total_return"]), "final_nav": float(s["final_nav_with_accrued_dividends"]),
        "mdd": float(s["mdd"]["include_initial_nav_true"]), "mdd_excl_initial": float(s["mdd"]["include_initial_nav_false"]),
        "daily_vol": s["daily_vol"], "turnover": float(s["cum_turnover"]),
        "turnover_after_day1": s["turnover_after_day1"],
        "transaction_cost": float(s["cost_pct_initial"]),
        "avg_holdings": s["avg_holdings"], "avg_cash": s["avg_cash"],
        "active_share_min": s["active_share_min"], "violations": s["warning_count"], "dq": s["dq"],
        "fallbacks": s["fallback_days"], "validation_failures": s["validation_failures"],
        "orders_per_day": s["avg_orders_per_day"], "orders_per_day_after_day1": s["avg_orders_after_day1"],
        **ich, "git_sha": s["git_sha"], "config_hash": job["config_hash"], "dataset_version": job["dataset_version"],
        "runtime_sec": round(time.perf_counter() - t0, 1), "avg_day_runtime_sec": s["avg_day_runtime_sec"],
        "regime_days": json.dumps(daily["regime"].value_counts().to_dict(), ensure_ascii=False),
        "llm_calls": s.get("llm_calls", 0), "llm_tokens": s.get("llm_tokens", 0), "llm_cost": s.get("llm_cost", 0),
        "llm_failed": s.get("llm_failed", 0), "llm_latency": s.get("llm_latency_p95_max", 0),
        "event_count": s.get("event_count", 0), "events_hallucinated": s.get("events_hallucinated", 0),
        "events_raw": s.get("events_raw", 0), "events_schema_fail": s.get("events_schema_fail", 0),
        "narrative_llm_days": s.get("narrative_llm_days", 0), "guard_days": s.get("guard_days"),
        "p95_day_runtime_sec": s.get("p95_day_runtime_sec"),
    }
    return row


def _precompute(args):
    history, as_of, d = args
    from agent.pipeline import cached_features
    st = HistoryStore(history)
    cached_features(st, as_of, d, sorted(load_universe()))
    return d


def precompute_features(history: str, wins: dict, workers: int) -> None:
    store = HistoryStore(history)
    cal = TradingCalendar(store.dates("daily_prices"))
    todo = sorted({d for w in wins.values() for d in window_days(cal, w["start"])})
    with ProcessPoolExecutor(max_workers=workers) as ex:
        list(ex.map(_precompute, [(history, f"{d}T07:00:00+08:00", d) for d in todo]))
    print(f"precomputed features for {len(todo)} dates", flush=True)


def dataset_version(store: HistoryStore) -> str:
    from agent.pipeline import _store_fingerprint
    from agent.pipeline import FEATURE_TABLES
    return _store_fingerprint(store, FEATURE_TABLES)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default="main")
    ap.add_argument("--only", default=None, help="comma-separated strategy ids")
    ap.add_argument("--groups", default=None, help="comma-separated groups")
    ap.add_argument("--windows", default=None, help="comma-separated window ids")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--history", default=str(ROOT / "data" / "history"))
    ap.add_argument("--random-only", action="store_true")
    ap.add_argument("--stress", default=None, help="comma-separated strategy ids for cost/slippage stress")
    ap.add_argument("--extra", default=None, help="YAML file with extra strategies (sensitivity)")
    ap.add_argument("--out", default=None, help="leaderboard csv path")
    ap.add_argument("--r04", action="store_true", help="use the Round 04 registry (Quant v1 vs LLM vs Crash Guard)")
    a = ap.parse_args(argv)
    REPORTS.mkdir(exist_ok=True)
    store = HistoryStore(a.history)
    wfile = REPORTS / "windows.json"
    wins = json.loads(wfile.read_text(encoding="utf-8"))
    if a.windows:
        wins = {k: v for k, v in wins.items() if k in a.windows.split(",")}
    cal = TradingCalendar(store.dates("daily_prices"))

    if a.random_only:
        rows = []
        for wid, w in wins.items():
            ds = window_days(cal, w["start"])
            r = random_mc(store, ds)
            ref = buy_hold_refs(store, ds)
            rows.append({"window": wid, "start": ds[0], "end": ds[-1], "n": len(r),
                         **{f"p{q}": float(np.percentile(r, q)) for q in (5, 10, 25, 50, 75, 90, 95)},
                         "mean": float(r.mean()), **ref})
            np.save(REPORTS / f"random_mc_{wid}.npy", r)
        pd.DataFrame(rows).to_csv(REPORTS / "random_baseline.csv", index=False, encoding="utf-8-sig")
        print(pd.DataFrame(rows).to_string())
        return

    base = load_strategy()
    if a.r04:
        from agent.research.strategies_r04 import registry_r04, resolve_r04
        strategies = registry_r04()
    else:
        strategies = registry()
    if a.extra:
        strategies += yaml.safe_load(Path(a.extra).read_text(encoding="utf-8"))
    if a.only:
        keep = set(a.only.split(","))
        strategies = [s for s in strategies if s["strategy_id"] in keep]
    if a.groups:
        g = set(a.groups.split(","))
        strategies = [s for s in strategies if s["group"] in g]
    dv = dataset_version(store)
    out_root = ROOT / "sim_runs" / "round03" / a.batch
    jobs = []
    variants = [("official", 1.0, 0.0, [])]
    stress_ids = set(a.stress.split(",")) if a.stress else set()
    for st in strategies:
        cfg = resolve_r04(st) if a.r04 else resolve(base, st)
        vlist = variants + ([("cost_x1.25", 1.25, 0.0, []), ("cost_x1.5", 1.5, 0.0, []),
                             ("slip_20bp", 1.0, 0.002, [])] if st["strategy_id"] in stress_ids else [])
        for wid, w in wins.items():
            for vname, cm, sl, fl in vlist:
                jobs.append({"strategy_id": st["strategy_id"], "group": st["group"], "cfg": cfg, "window": w,
                             "wid": wid, "run_id": f"{st['strategy_id']}__{wid}__{vname}", "out_root": str(out_root),
                             "config_hash": config_hash(cfg), "dataset_version": dv, "variant": vname,
                             "cost_mult": cm, "slippage": sl, "faults": fl})
    precompute_features(a.history, wins, a.workers)
    print(f"{len(strategies)} strategies × {len(wins)} windows → {len(jobs)} jobs, {a.workers} workers", flush=True)
    rows, t0 = [], time.time()
    with ProcessPoolExecutor(max_workers=a.workers, initializer=_init_worker, initargs=(a.history,)) as ex:
        futs = [ex.submit(run_job, j) for j in jobs]
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            rows.append(r)
            if "error" in r:
                print("ERROR", r["strategy_id"], r["window"], r["error"][:300], flush=True)
            elif i % 10 == 0 or i == len(jobs):
                print(f"{i}/{len(jobs)} done ({time.time() - t0:.0f}s)", flush=True)
    df = pd.DataFrame(rows)
    rnd = REPORTS / "random_baseline.csv"
    if rnd.exists() and "return" in df:
        for wid in df["window"].unique():
            f = REPORTS / f"random_mc_{wid}.npy"
            if f.exists():
                arr = np.load(f)
                m = df["window"] == wid
                df.loc[m, "random_percentile"] = df.loc[m, "return"].map(lambda x: float((arr < x).mean() * 100))
    path = Path(a.out) if a.out else REPORTS / f"leaderboard_{a.batch}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print("wrote", path, len(df), "rows")


if __name__ == "__main__":
    main()
