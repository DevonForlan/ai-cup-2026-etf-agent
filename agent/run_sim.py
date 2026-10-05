"""Walk-forward competition simulation.

  python agent\\run_sim.py --start 2026-08-31 --end 2026-10-02 --method B0_score_tiered
  python agent\\run_sim.py --start 2026-08-31 --end 2026-10-02 --all-baselines
  python agent\\run_sim.py --config config\\strategy_quant_v1.yaml --start 2026-08-28 --days 24

Each day: run_day (PIT as of T 07:00) -> D-Plan -> settle at T VWAP / close -> next day.
Outputs sim_runs/<run_id>/: config snapshot, dplan/, settlement/, validation/, daily.csv, summary.json
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import shutil
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.config import ROOT, D, load_strategy  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.engine.active_share import compute_active_share  # noqa: E402
from agent.engine.rules import RuleBook, load_rulebook  # noqa: E402
from agent.pipeline import (as_of_weights, cached_features, code_version, day_market, llm_settings,  # noqa: E402
                            run_day, update_state_after_settlement, working_tree_dirty)
from agent.sim.calendar import TradingCalendar  # noqa: E402
from agent.sim.metrics import summarize  # noqa: E402
from agent.sim.models import Settlement  # noqa: E402
from agent.sim.settle import settle  # noqa: E402


def research_rulebook(rb: RuleBook, cost_mult: float = 1.0, fee_rounding: str | None = None) -> RuleBook:
    """RESEARCH-ONLY variants (cost stress, rounding). Never used for the official estimate."""
    r = rb.rules
    if cost_mult != 1.0:
        m = D(str(cost_mult))
        r = dataclasses.replace(r, buy_fee_rate=r.buy_fee_rate * m, sell_fee_rate=r.sell_fee_rate * m,
                                transaction_tax_rate=r.transaction_tax_rate * m)
    a = rb.assumptions.with_overrides(fee_rounding_mode=fee_rounding) if fee_rounding else rb.assumptions
    return RuleBook(r, rb.universe, rb.active_etfs, a)


def simulate(start: str, end: str | None = None, *, history: Path, method: str | None = None,
             cfg: dict | None = None, cfg_path: str = "config/strategy.yaml", days: int | None = None,
             initial_cash=None, run_id: str | None = None, team_id: str = "TEAM_SIM", fixture: bool = False,
             out_root: Path | None = None, fee_rounding: str | None = None, quiet: bool = False,
             light: bool = False, cost_mult: float = 1.0, slippage: float = 0.0,
             data_faults: set[str] | None = None, store: HistoryStore | None = None,
             keep_scores: bool = False, strategy_id: str | None = None, narrative: str | None = None,
             llm_provider: str | None = None, llm_config: str = "config/llm.yaml") -> dict:
    cfg = copy.deepcopy(cfg) if cfg is not None else load_strategy(cfg_path)
    rb = research_rulebook(load_rulebook(), cost_mult, fee_rounding)
    store = store or HistoryStore(history)
    cal = TradingCalendar(store.dates("daily_prices"))
    all_days = [d for d in cal.days if d >= start]
    sim_days = all_days[:days] if days else [d for d in all_days if end is None or d <= end]
    if not sim_days:
        raise SystemExit(f"no trading days with data from {start}")
    method = method or cfg["baseline"]["method"]
    run_id = run_id or f"{datetime.now():%Y%m%d_%H%M%S}_{method}_{sim_days[0]}_{sim_days[-1]}"
    root = (out_root or ROOT / "sim_runs") / run_id
    for sub in ("dplan", "settlement", "validation", "logs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "strategy.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    shutil.copy(ROOT / "config" / "competition.yaml", root / "competition.yaml")
    shutil.copy(ROOT / "config" / "unconfirmed_rules.yaml", root / "unconfirmed_rules.yaml")

    init = D(initial_cash) if initial_cash is not None else rb.rules.initial_cash
    prev = Settlement.initial(cal.prev(sim_days[0]) or "initial", init)
    settlements, rows, score_log, decision_log = [], [], {}, {}
    bmult = D(str(1 + slippage)) if slippage else None
    smult = D(str(1 - slippage)) if slippage else None
    t_start = time.perf_counter()
    llm = llm_settings(cfg, narrative, llm_provider, llm_config, log_root=root / "llm")
    if llm is not None:
        from agent.llm.client import make_provider
        llm["provider"] = make_provider(llm["cfg"])           # one provider per run (budgets are per day)
        (root / "llm.yaml").write_text(yaml.safe_dump(llm["cfg"], allow_unicode=True, sort_keys=False), encoding="utf-8")
    llm_rows = []
    for d in sim_days:
        r = run_day(d, store, prev, rb, cfg, team_id=team_id, mode="replay", out_dir=root / "dplan",
                    log_dir=root / "logs" / d.replace("-", ""), method=method, store_is_fixture=fixture,
                    calendar=cal, light=light, data_faults=data_faults, llm=llm)
        if not light:
            (root / "validation" / f"{d}.json").write_text(json.dumps(r.validation.to_dict(), ensure_ascii=False,
                                                                      indent=1, default=str), encoding="utf-8")
        mkt = day_market(store, d)
        orders = r.doc["orders"] if r.validation.ok else None
        s = settle(prev, orders, mkt, rb, buy_price_mult=bmult, sell_price_mult=smult)
        s.agent_state = update_state_after_settlement(r.agent_state, prev.holdings, s.holdings, d)
        # end-of-day Active Share (settled weights at close) vs the ETF top-10 visible today
        as_min, as_etf = None, None
        _, etf_h, etf_meta, *_ = cached_features(store, f"{d}T07:00:00+08:00", d, sorted(rb.universe))
        if etf_h and s.holdings:
            res = compute_active_share(as_of_weights(s.holdings, s.closes, s.cash), etf_h, rb.active_etfs,
                                       rb.assumptions.active_share_mode, etf_meta.get("date"),
                                       etf_meta.get("synthetic"))
            as_min, as_etf = res.minimum_active_share, res.benchmark_ticker
            if as_min is not None:
                s.active_share_breach_days = (prev.active_share_breach_days + 1
                                              if as_min < rb.rules.active_share_min else 0)
                if (s.active_share_breach_days >= rb.rules.active_share_consecutive_days_dq
                        and "ACTIVE_SHARE_2D" not in s.dq_reasons):
                    s.dq_reasons.append("ACTIVE_SHARE_2D")
                    s.dq = True
        s.save(root / "settlement" / f"{d}.json")
        settlements.append(s)
        n_trades = len(r.doc["orders"])
        rows.append({"date": d, "nav": str(s.nav), "cash": str(s.cash), "cash_ratio": float(s.cash / s.nav),
                     "holdings": len(s.holdings), "orders": n_trades, "fallback": r.fallback,
                     "validation_ok": r.validation.ok, "turnover": float(s.turnover), "fees": str(s.fees),
                     "tax": str(s.tax), "warnings": "; ".join(w["rule"] for w in s.warnings),
                     "trades_void": s.trades_void, "active_share_min": None if as_min is None else float(as_min),
                     "active_share_etf": as_etf, "regime": (r.agent_state.get("regime") or {}).get("regime")
                     if r.agent_state.get("regime") else getattr(r.result, "regime", None),
                     "etf_real": (r.etf_meta or {}).get("n_real"), "runtime_sec": round(r.timings.get("total", 0), 3),
                     "guard_state": (r.guard or {}).get("state"), "guard_points": (r.guard or {}).get("points"),
                     "llm_calls": r.llm_summary.get("calls", 0), "llm_failed": r.llm_summary.get("failed", 0),
                     "llm_tokens": r.llm_summary.get("input_tokens", 0) + r.llm_summary.get("output_tokens", 0),
                     "llm_cost": r.llm_summary.get("cost_usd", 0), "llm_latency_p95": r.llm_summary.get("latency_p95", 0),
                     "narrative_llm": r.narrative_used_llm, "events": len(r.events),
                     "events_hallucinated": r.event_stats.get("hallucinations", 0),
                     "events_schema_fail": r.event_stats.get("schema_failures", 0),
                     "events_raw": r.event_stats.get("events_raw", 0)})
        llm_rows.append({"date": d, "events": [e.__dict__ for e in r.events]})
        if keep_scores and r.scores is not None:
            score_log[d] = r.scores[["raw_score", "score", "rank", "eligible"]].copy()
            decision_log[d] = [(x["ticker"], x["action"]) for x in r.doc["decisions"]]
        if not quiet:
            print(f"{d} NAV {float(s.nav):>16,.0f} hold {len(s.holdings):2d} ord {n_trades:2d} "
                  f"cash {float(s.cash / s.nav):6.2%} val {'OK' if r.validation.ok else 'FAIL'}"
                  f"{' FALLBACK' if r.fallback else ''}{' WARN:' + rows[-1]['warnings'] if s.warnings else ''}",
                  flush=True)
        prev = s
    pd.DataFrame(rows).to_csv(root / "daily.csv", index=False, encoding="utf-8-sig")
    summ = summarize(settlements, init)
    daily = pd.DataFrame(rows)
    navs = [init] + [s.nav for s in settlements]
    rets = [float(navs[i + 1] / navs[i] - 1) for i in range(len(navs) - 1)]
    summ.update({
        "run_id": run_id, "strategy_id": strategy_id or run_id, "method": method,
        "start": sim_days[0], "end": sim_days[-1], "fixture": fixture,
        "git_sha": code_version(), "tree_dirty": working_tree_dirty(),
        "validation_failures": int((~daily["validation_ok"]).sum()),
        "fallback_days": int(daily["fallback"].sum()),
        "illegal_portfolio_days": sum(1 for s in settlements if s.warnings),
        "daily_vol": float(pd.Series(rets).std()) if len(rets) > 1 else 0.0,
        "avg_cash": float(daily["cash_ratio"].mean()),
        "avg_orders_per_day": float(daily["orders"].mean()),
        "avg_orders_after_day1": float(daily["orders"].iloc[1:].mean()) if len(daily) > 1 else 0.0,
        "turnover_after_day1": float(daily["turnover"].iloc[1:].sum()) if len(daily) > 1 else 0.0,
        "active_share_min": None if daily["active_share_min"].isna().all() else float(daily["active_share_min"].min()),
        "cost_mult": cost_mult, "slippage": slippage, "faults": sorted(data_faults or []),
        "runtime_sec": round(time.perf_counter() - t_start, 1),
        "avg_day_runtime_sec": float(daily["runtime_sec"].mean()),
        "p95_day_runtime_sec": float(daily["runtime_sec"].quantile(0.95)),
        "llm_calls": int(daily["llm_calls"].sum()), "llm_tokens": int(daily["llm_tokens"].sum()),
        "llm_cost": float(daily["llm_cost"].fillna(0).sum()), "llm_failed": int(daily["llm_failed"].sum()),
        "llm_latency_p95_max": float(daily["llm_latency_p95"].max()),
        "event_count": int(daily["events"].sum()), "events_hallucinated": int(daily["events_hallucinated"].sum()),
        "events_raw": int(daily["events_raw"].sum()), "events_schema_fail": int(daily["events_schema_fail"].sum()),
        "narrative_llm_days": int(daily["narrative_llm"].sum()),
        "guard_days": json.dumps(daily["guard_state"].value_counts().to_dict()) if daily["guard_state"].notna().any() else None,
    })
    (root / "events.json").write_text(json.dumps(llm_rows, ensure_ascii=False, indent=0, default=str), encoding="utf-8")
    (root / "summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if keep_scores:
        summ["_scores"] = score_log
        summ["_decisions"] = decision_log
        summ["_daily"] = daily
    return summ


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Walk-forward competition simulation")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", default=None)
    ap.add_argument("--days", type=int, default=None, help="number of trading days from --start")
    ap.add_argument("--method", default=None)
    ap.add_argument("--all-baselines", action="store_true")
    ap.add_argument("--config", default="config/strategy.yaml")
    ap.add_argument("--history", default=str(ROOT / "data" / "history"))
    ap.add_argument("--initial-cash", default=None)
    ap.add_argument("--fee-rounding", default=None, choices=["exact", "round_half_up", "floor", "ceil"])
    ap.add_argument("--cost-mult", type=float, default=1.0, help="RESEARCH stress: multiply fees+tax")
    ap.add_argument("--slippage", type=float, default=0.0, help="RESEARCH stress: buy VWAP×(1+s), sell×(1−s)")
    ap.add_argument("--fixture", action="store_true")
    ap.add_argument("--light", action="store_true")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--narrative", choices=["template", "llm"], default=None)
    ap.add_argument("--llm-provider", default=None, help="mock|replay|template|google|openai|anthropic")
    ap.add_argument("--llm-config", default="config/llm.yaml")
    a = ap.parse_args(argv)
    if working_tree_dirty():
        print(f"[warning] working tree dirty -> code_version={code_version()}")
    methods = ["B0_score_tiered", "B1_score_equal", "B2_momentum", "B3_institutional"] if a.all_baselines else [a.method]
    for m in methods:
        rid = None if not a.run_id else (a.run_id + ("" if len(methods) == 1 else f"_{m}"))
        s = simulate(a.start, a.end, days=a.days, history=Path(a.history), method=m, cfg_path=a.config,
                     initial_cash=a.initial_cash, run_id=rid, fixture=a.fixture, fee_rounding=a.fee_rounding,
                     light=a.light, cost_mult=a.cost_mult, slippage=a.slippage, narrative=a.narrative,
                     llm_provider=a.llm_provider, llm_config=a.llm_config)
        print(json.dumps({k: s[k] for k in ("run_id", "final_nav", "total_return", "mdd", "cum_turnover",
                                             "cum_fees", "cum_tax", "warning_count", "dq", "validation_failures",
                                             "fallback_days", "git_sha", "runtime_sec")},
                         default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
