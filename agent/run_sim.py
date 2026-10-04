"""Walk-forward competition simulation.

  python agent\\run_sim.py --start 2026-08-31 --end 2026-10-02 --method B0_score_tiered
  python agent\\run_sim.py --start 2026-08-31 --end 2026-10-02 --all-baselines

Each day: run_day (PIT as of T 07:00) -> D-Plan -> settle at T VWAP / close -> next day.
Outputs sim_runs/<run_id>/: config snapshot, dplan/, settlement/, validation/, daily.csv, summary.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.config import ROOT, D, load_strategy  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.data.pit import PITView  # noqa: E402
from agent.engine.active_share import compute_active_share  # noqa: E402
from agent.engine.rules import load_rulebook  # noqa: E402
from agent.pipeline import as_of_weights, day_market, etf_holdings_from_view, run_day  # noqa: E402
from agent.sim.calendar import TradingCalendar  # noqa: E402
from agent.sim.metrics import summarize  # noqa: E402
from agent.sim.models import Settlement  # noqa: E402
from agent.sim.settle import settle  # noqa: E402


def simulate(start: str, end: str, *, history: Path, method: str | None, cfg_path: str = "config/strategy.yaml",
             initial_cash=None, run_id: str | None = None, team_id: str = "TEAM_SIM", fixture: bool = False,
             out_root: Path | None = None, fee_rounding: str | None = None, quiet: bool = False) -> dict:
    cfg = load_strategy(cfg_path)
    rb = load_rulebook()
    if fee_rounding:
        rb = rb.__class__(rb.rules, rb.universe, rb.active_etfs, rb.assumptions.with_overrides(fee_rounding_mode=fee_rounding))
    store = HistoryStore(history)
    cal = TradingCalendar(store.dates("daily_prices"))
    days = cal.between(start, end)
    if not days:
        raise SystemExit(f"no trading days with data between {start} and {end}")
    method = method or cfg["baseline"]["method"]
    run_id = run_id or f"{datetime.now():%Y%m%d_%H%M%S}_{method}_{start}_{end}"
    root = (out_root or ROOT / "sim_runs") / run_id
    for sub in ("dplan", "settlement", "validation", "logs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / cfg_path, root / "strategy.yaml")
    shutil.copy(ROOT / "config" / "competition.yaml", root / "competition.yaml")
    shutil.copy(ROOT / "config" / "unconfirmed_rules.yaml", root / "unconfirmed_rules.yaml")

    init = D(initial_cash) if initial_cash is not None else rb.rules.initial_cash
    prev = Settlement.initial(cal.prev(days[0]) or "initial", init)
    settlements, rows = [], []
    for d in days:
        r = run_day(d, store, prev, rb, cfg, team_id=team_id, mode="replay", out_dir=root / "dplan",
                    log_dir=root / "logs" / d.replace("-", ""), method=method, store_is_fixture=fixture, calendar=cal)
        (root / "validation" / f"{d}.json").write_text(json.dumps(r.validation.to_dict(), ensure_ascii=False,
                                                                  indent=1, default=str), encoding="utf-8")
        mkt = day_market(store, d)
        orders = r.doc["orders"] if r.validation.ok else None
        # end-of-day Active Share vs ETF top-10 (for the 2-consecutive-day DQ rule)
        etf_h, etf_meta = etf_holdings_from_view(PITView(store, f"{d}T23:59:59+08:00"))
        s = settle(prev, orders, mkt, rb)
        as_min = None
        if etf_h and s.holdings:
            res = compute_active_share(as_of_weights(s.holdings, s.closes, s.cash), etf_h, rb.active_etfs,
                                       rb.assumptions.active_share_mode, etf_meta.get("date"), etf_meta.get("synthetic"))
            as_min = res.minimum_active_share
            if as_min is not None:
                s = settle(prev, orders, mkt, rb, active_share_min=as_min)
        s.save(root / "settlement" / f"{d}.json")
        settlements.append(s)
        rows.append({"date": d, "nav": str(s.nav), "cash": str(s.cash), "cash_ratio": float(s.cash / s.nav),
                     "holdings": len(s.holdings), "orders": len(r.doc["orders"]), "fallback": r.fallback,
                     "validation_ok": r.validation.ok, "turnover": float(s.turnover), "fees": str(s.fees),
                     "tax": str(s.tax), "warnings": "; ".join(w["rule"] for w in s.warnings),
                     "trades_void": s.trades_void, "active_share_min": None if as_min is None else float(as_min)})
        if not quiet:
            print(f"{d} NAV {float(s.nav):>16,.0f} hold {len(s.holdings):2d} ord {len(r.doc['orders']):2d} "
                  f"cash {float(s.cash / s.nav):6.2%} val {'OK' if r.validation.ok else 'FAIL'}"
                  f"{' FALLBACK' if r.fallback else ''}{' WARN:' + rows[-1]['warnings'] if s.warnings else ''}", flush=True)
        prev = s
    import pandas as pd
    pd.DataFrame(rows).to_csv(root / "daily.csv", index=False, encoding="utf-8-sig")
    summ = summarize(settlements, init)
    summ.update({"run_id": run_id, "method": method, "start": days[0], "end": days[-1], "fixture": fixture,
                 "validation_failures": sum(1 for x in rows if not x["validation_ok"]),
                 "fallback_days": sum(1 for x in rows if x["fallback"]),
                 "illegal_portfolio_days": sum(1 for s in settlements if s.warnings)})
    (root / "summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return summ


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Walk-forward competition simulation")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--method", default=None)
    ap.add_argument("--all-baselines", action="store_true")
    ap.add_argument("--config", default="config/strategy.yaml")
    ap.add_argument("--history", default=str(ROOT / "data" / "history"))
    ap.add_argument("--initial-cash", default=None)
    ap.add_argument("--fee-rounding", default=None, choices=["exact", "round_half_up", "floor", "ceil"])
    ap.add_argument("--fixture", action="store_true")
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args(argv)
    methods = ["B0_score_tiered", "B1_score_equal", "B2_momentum", "B3_institutional"] if a.all_baselines else [a.method]
    results = {}
    for m in methods:
        rid = None if not a.run_id else (a.run_id + ("" if len(methods) == 1 else f"_{m}"))
        s = simulate(a.start, a.end, history=Path(a.history), method=m, cfg_path=a.config,
                     initial_cash=a.initial_cash, run_id=rid, fixture=a.fixture, fee_rounding=a.fee_rounding)
        results[s["method"]] = s
        print(json.dumps({k: s[k] for k in ("run_id", "final_nav", "total_return", "mdd", "cum_turnover",
                                             "cum_fees", "cum_tax", "warning_count", "dq",
                                             "validation_failures", "fallback_days")}, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
