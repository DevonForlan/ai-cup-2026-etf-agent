"""One-command daily run. Produces a READY_TO_SUBMIT package and a FINAL_CANDIDATE marker.
It NEVER uploads, logs in, automates a browser or calls any official endpoint (NC-1 unconfirmed).

  python agent\\competition_day.py --date 2026-10-27 --team-id TEAM_TEST --mode dry-run
  python agent\\competition_day.py --date 2026-10-02 --team-id TEAM_TEST --mode historical --replay-run sim_runs\\round05_baseline_quant_v1
  python agent\\competition_day.py --date 2026-10-27 --team-id TEAM_042 --mode competition [--llm-config config\\llm_narrative_v1.yaml]

Flow: DEADLINE GUARD -> DATA REFRESH -> SETTLEMENT + RECONCILIATION -> PREFLIGHT -> PIT SNAPSHOT ->
QUANT CORE v1 -> PORTFOLIO -> COMPLIANCE -> ORDERS -> NARRATIVE -> D-PLAN -> VALIDATION ->
SUBMISSION PACKAGE -> FINAL_CANDIDATE -> ARCHIVE -> OPERATOR SUMMARY.

Safe degradation: L0 quant + approved real-LLM narrative | L1 quant + template narrative |
L2 quant with cached/stale optional data | L3 deterministic fallback (previous legal portfolio).
Every level must pass the competition validator; otherwise status = BLOCKED and no FINAL_CANDIDATE.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.config import ROOT, D, load_strategy  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.engine.rules import load_rulebook  # noqa: E402
from agent.ops import deadline as DL  # noqa: E402
from agent.ops.archive_run import archive_run, run_id_for  # noqa: E402
from agent.ops.common import (BLOCK, TPE, Clock, load_ops_config, ops_logger, ops_path, sha256_file,  # noqa: E402
                              sha256_json, write_json, ymd)
from agent.ops.package_submission import build_package, mark_final  # noqa: E402
from agent.ops.preflight import config_hashes, git_info, prompt_versions, run_preflight  # noqa: E402
from agent.ops.reconcile import reconcile  # noqa: E402
from agent.ops.settlement import (ManualFileSettlementProvider, ReplaySettlementProvider, apply_official,  # noqa: E402
                                  load_internal, normalize_official, path_for)
from agent.pipeline import code_version, llm_settings, run_day  # noqa: E402
from agent.sim.calendar import TradingCalendar  # noqa: E402
from agent.sim.models import Settlement  # noqa: E402


def _closes_on(store: HistoryStore, d: str) -> dict:
    p = store.load("daily_prices")
    p = p[p["date"] == d]
    return {r.ticker: D(round(float(r.close), 4)) for r in p.itertuples() if r.close == r.close}


def run_competition_day(trade_date: str, team_id: str, mode: str = "dry-run", *,
                        config: str = "config/strategy_quant_v1.yaml", llm_config: str | None = None,
                        clock: Clock | None = None, ops_cfg: dict | None = None, store: HistoryStore | None = None,
                        refresh_fetchers: dict | None = None, skip_refresh: bool = False,
                        settlement_provider=None, initial: bool = False, replay_run: str | None = None,
                        data_faults: set | None = None, git: dict | None = None, llm_provider=None,
                        archive_readonly: bool = True) -> dict:
    t_start = time.perf_counter()
    ops_cfg = ops_cfg or load_ops_config()
    clock = clock or Clock()
    store = store or HistoryStore()
    rb = load_rulebook()
    cfg = load_strategy(config)
    lg = ops_logger(trade_date, "competition_day", ops_cfg)
    durations, notes = {}, []
    summary = {"trade_date": trade_date, "team_id": team_id, "mode": mode, "status": "RUNNING",
               "started_at": clock.now().isoformat()}

    def finish(status: str, **kw):
        summary.update(kw, status=status, total_sec=round(time.perf_counter() - t_start, 2), durations=durations,
                       notes=notes, finished_at=clock.now().isoformat())
        write_json(ops_path(ops_cfg, "ops_logs_dir") / ymd(trade_date) / "competition_day_summary.json", summary)
        lg.info(f"STATUS {status} {json.dumps({k: summary.get(k) for k in ('final_file', 'sha256', 'reason')}, ensure_ascii=False)}")
        return summary

    # ---------------------------------------------------------------- deadline
    dls = DL.status(trade_date, clock, ops_cfg)
    summary["deadline"] = dls.to_dict()
    lg.info(f"deadline phase {dls.phase} ({dls.minutes_left:.1f} min left)")
    # ---------------------------------------------------------------- data refresh
    t0 = time.perf_counter()
    data_health = None
    if mode != "historical" and not skip_refresh and dls.allow_refresh:
        from agent.ops.refresh_daily import refresh
        data_health = refresh(trade_date, store=store, fetchers=refresh_fetchers, ops_cfg=ops_cfg, clock=clock,
                              allow_noncritical=dls.allow_noncritical_refresh)
        store._cache.clear()
    elif mode != "historical":
        notes.append(f"data refresh skipped ({'deadline ' + dls.phase if not dls.allow_refresh else 'requested'})")
    durations["data_refresh"] = round(time.perf_counter() - t0, 2)
    # ---------------------------------------------------------------- settlement + reconciliation
    t0 = time.perf_counter()
    cal = TradingCalendar(store.dates("daily_prices") + [trade_date])
    prev_date = cal.prev(trade_date)
    sstat = {"previous_date": prev_date, "initial_day": initial}
    rec = None
    start: Settlement | None = None
    if initial:
        start = Settlement.initial(prev_date or "initial", rb.rules.initial_cash)
        sstat.update(previous_available=True, source="initial cash")
    else:
        replay = ReplaySettlementProvider(Path(replay_run), ops_cfg) if replay_run else None
        internal = load_internal(prev_date, ops_cfg) or (replay.settlement(prev_date) if replay else None)
        provider = settlement_provider or (replay if (replay and mode != "competition") else
                                           ManualFileSettlementProvider(ops_cfg))
        official = provider.get(prev_date) if provider else None
        if internal is not None and official is not None:
            idict = {"holdings": internal.holdings, "cash": str(internal.cash), "nav": str(internal.nav),
                     "accrued_dividends": str(internal.accrued_dividends),
                     "warnings": [w["rule"] for w in internal.warnings]}
            rec = reconcile(idict, official, ops_cfg)
            rec["date"] = prev_date
            write_json(path_for(prev_date, "reconciliation", ops_cfg), rec)
            sstat["reconciliation"] = rec["status"]
            if rec["status"] != "BLOCK":
                start = apply_official(internal, official)
                sstat.update(previous_available=True, source=f"official ({official.get('source')}) + internal state")
        elif internal is not None:
            sstat["reconciliation"] = "UNAVAILABLE"
            start = internal
            sstat.update(previous_available=True, source="INTERNAL ONLY (official settlement missing)")
        elif official is not None:
            sstat["reconciliation"] = "UNAVAILABLE"
            start = Settlement(prev_date, official["holdings"], D(official["cash"]),
                               D(official["nav"]) if official.get("nav") else D(official["cash"]),
                               initial_nav=rb.rules.initial_cash)
            sstat.update(previous_available=True, source="OFFICIAL ONLY (no internal state)")
        else:
            sstat["previous_available"] = False
    summary["settlement"] = sstat
    summary["reconciliation"] = rec
    durations["settlement"] = round(time.perf_counter() - t0, 2)
    # ---------------------------------------------------------------- preflight
    t0 = time.perf_counter()
    closes_prev = _closes_on(store, prev_date) if prev_date else {}
    pf = run_preflight(trade_date, mode="competition" if mode == "competition" else "dry-run", strategy_cfg=config,
                       llm_cfg=llm_config, clock=clock, ops_cfg=ops_cfg, data_health=data_health,
                       settlement_status=sstat, prev_holdings=start.holdings if start else None,
                       prev_cash=start.cash if start else None, closes_prev=closes_prev, git=git)
    summary["preflight"] = {"level": pf["level"], "blocks": [c for c in pf["checks"] if c["level"] == BLOCK],
                            "warns": [c["name"] for c in pf["checks"] if c["level"] == "WARN"]}
    durations["preflight"] = round(time.perf_counter() - t0, 2)
    if pf["level"] == BLOCK or start is None:
        return finish("BLOCKED", reason="preflight BLOCK: " + "; ".join(f"{c['name']}: {c['detail']}" for c in
                                                                        summary["preflight"]["blocks"])[:600])
    # ---------------------------------------------------------------- quant core + narrative + D-Plan + validation
    t0 = time.perf_counter()
    llm = None
    if llm_config and dls.allow_llm:
        llm = llm_settings(cfg, None, None, llm_config, provider_instance=llm_provider)
        if llm is not None and not dls.allow_noncritical_refresh:
            llm["cfg"]["retries"] = 0                      # restricted phase: no LLM retries
    elif llm_config:
        notes.append(f"LLM disabled by deadline guard ({dls.phase}) -> template narrative")
    out_dir = ops_path(ops_cfg, "ops_logs_dir") / ymd(trade_date) / "dplan_work"
    as_of = None if mode == "historical" else clock.now().replace(microsecond=0).isoformat()
    try:
        r = run_day(trade_date, store, start, rb, cfg, team_id=team_id, mode="replay", out_dir=out_dir,
                    log_dir=ops_path(ops_cfg, "ops_logs_dir") / ymd(trade_date) / "run", calendar=cal,
                    llm=llm, as_of_override=as_of, data_faults=data_faults)
    except Exception as e:  # noqa: BLE001
        lg.error(traceback.format_exc())
        return finish("BLOCKED", reason=f"program error in run_day: {type(e).__name__}: {e}"[:400])
    durations["quant_dplan_validation"] = round(time.perf_counter() - t0, 2)
    durations.update({f"run_day.{k}": round(v, 3) for k, v in r.timings.items()})
    level = 3 if r.fallback else (0 if r.narrative_used_llm else
                                  (2 if data_health and data_health["level"] != "PASS" else 1))
    tp = r.result
    summary.update({
        "degradation_level": level, "fallback": r.fallback, "validation": "PASS" if r.validation.ok else "FAIL",
        "validation_summary": r.validation.summary(),
        "portfolio": {"holdings_after": len(getattr(tp, "est_holdings", {}) or start.holdings),
                      "cash_ratio_est": float(getattr(tp, "cash_weight_est", 0) or 0),
                      "regime": r.doc["market_view"]["regime"], "posture": r.doc["market_view"]["posture"]},
        "active_share_min": None if r.active_share is None or r.active_share.minimum_active_share is None
        else float(r.active_share.minimum_active_share),
        "orders": len(r.doc["orders"]), "decisions": len(r.doc["decisions"]),
        "llm": {"used": r.narrative_used_llm, **{k: r.llm_summary.get(k) for k in ("calls", "failed", "latency_p95")}}
        if llm else {"used": False, "mode": "template"},
    })
    if not r.validation.ok:
        return finish("BLOCKED", reason="D-Plan validation FAIL even after deterministic fallback "
                                        "(previous portfolio may be illegal: see EMERGENCY_RUNBOOK)")
    # ---------------------------------------------------------------- package + final + archive
    t0 = time.perf_counter()
    g = git or git_info()
    gsha = code_version()
    run_id = run_id_for(clock.now(), gsha)
    meta = {"trade_date": trade_date, "generated_at": clock.now().isoformat(), "git_sha": gsha,
            "git_dirty": bool(g["dirty_paths"]), "python_version": platform.python_version(),
            "config_hashes": config_hashes(config, llm_config), "prompt_versions": prompt_versions(),
            "data_snapshot_hash": (data_health or {}).get("store_manifest_hash"),
            "settlement_hash": sha256_json({"holdings": start.holdings, "cash": str(start.cash), "nav": str(start.nav)}),
            "provider": (llm["cfg"].get("provider") if llm else "template"),
            "model": (llm["cfg"].get("model") if llm else None),
            "llm_replay_id": f"logs/llm/{ymd(trade_date)}/calls.jsonl" if llm else None,
            "degradation_level": level, "deadline": dls.to_dict(), "run_durations": durations}
    pkg = build_package(r, team_id=team_id, trade_date=trade_date, run_id=run_id, mode=mode,
                        data_health=data_health, reconciliation=rec, preflight=pf, run_metadata=meta, ops_cfg=ops_cfg,
                        extra_json={"agent_state.json": r.agent_state})
    fin = mark_final(pkg, team_id=team_id, trade_date=trade_date, mode=mode, ops_cfg=ops_cfg)
    durations["package"] = round(time.perf_counter() - t0, 2)
    t0 = time.perf_counter()
    arch = archive_run(trade_date, run_id, package_dir=pkg, ops_cfg=ops_cfg, readonly=archive_readonly,
                       config_files=[config, "config/competition.yaml", "config/unconfirmed_rules.yaml",
                                     "config/ops.yaml"] + ([llm_config] if llm_config else []))
    durations["archive"] = round(time.perf_counter() - t0, 2)
    if not fin["ok"]:
        return finish("BLOCKED", reason="FINAL_CANDIDATE refused: " + "; ".join(fin["reasons"]),
                      package=str(pkg), archive=str(arch))
    status = "READY_TO_SUBMIT" if mode == "competition" else ("DRY_RUN_OK" if mode == "dry-run" else "HISTORICAL_OK")
    if dls.phase == "PAST_CUTOFF":
        status = "LATE_PAST_CUTOFF"
    return finish(status, final_file=fin["path"], sha256=fin["sha256"], package=str(pkg), archive=str(arch),
                  run_id=run_id)


def operator_summary(s: dict) -> str:
    L = "=" * 70
    p = s.get("portfolio", {})
    lines = [L, f" TRADE DATE  : {s['trade_date']}     TEAM: {s['team_id']}     MODE: {s['mode'].upper()}",
             f" STATUS      : {s['status']}" + (f"   ({s.get('reason')})" if s.get("reason") else ""), L,
             f" DEADLINE    : {s.get('deadline', {}).get('phase')}  ({s.get('deadline', {}).get('minutes_left')} min left)",
             f" DATA        : {(s.get('preflight') or {}).get('level', '-')} preflight; warns={(s.get('preflight') or {}).get('warns', [])[:6]}",
             f" SETTLEMENT  : {s.get('settlement', {}).get('source', '-')}  reconciliation={s.get('settlement', {}).get('reconciliation', '-')}",
             f" PORTFOLIO   : regime={p.get('regime', '-')} posture={p.get('posture', {}).get('net_exposure_intent', '-')}",
             f" CASH        : {p.get('cash_ratio_est', 0):.2%} (estimate at T-1 close)" if p else " CASH        : -",
             f" HOLDINGS    : {p.get('holdings_after', '-')}",
             f" ACTIVE SHARE: {s.get('active_share_min')}",
             f" ORDERS      : {s.get('orders', '-')}  (decisions {s.get('decisions', '-')})",
             f" D-PLAN      : degradation level L{s.get('degradation_level', '-')}  fallback={s.get('fallback', '-')}",
             f" VALIDATION  : {s.get('validation', '-')}  {s.get('validation_summary', '')}",
             f" LLM         : {s.get('llm', {})}",
             f" FINAL FILE  : {s.get('final_file', '-- NONE --')}",
             f" SHA256      : {s.get('sha256', '-')}",
             f" ARCHIVE     : {s.get('archive', '-')}",
             f" RUNTIME     : {s.get('total_sec')} s", L]
    if s["mode"] != "competition" and s.get("final_file"):
        lines.insert(3, " *** DRY-RUN / HISTORICAL — NOT FOR SUBMISSION ***")
    return "\n".join(lines)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--team-id", required=True)
    ap.add_argument("--mode", choices=["dry-run", "historical", "competition"], default="dry-run")
    ap.add_argument("--config", default="config/strategy_quant_v1.yaml")
    ap.add_argument("--llm-config", default=None)
    ap.add_argument("--clock", default=None, help="simulated wall clock ISO +08:00 (dry-run / tests)")
    ap.add_argument("--skip-refresh", action="store_true")
    ap.add_argument("--initial", action="store_true", help="first competition day: start from initial cash")
    ap.add_argument("--replay-run", default=None, help="sim run dir used as settlement source (non-competition)")
    a = ap.parse_args(argv)
    if a.mode == "competition" and a.replay_run:
        print("--replay-run is not allowed in competition mode")
        return 2
    s = run_competition_day(a.date, a.team_id, a.mode, config=a.config, llm_config=a.llm_config,
                            clock=Clock(a.clock) if a.clock else None, skip_refresh=a.skip_refresh,
                            initial=a.initial, replay_run=a.replay_run)
    txt = operator_summary(s)
    print(txt)
    (ops_path(load_ops_config(), "ops_logs_dir") / ymd(a.date) / "operator_summary.txt").write_text(txt, encoding="utf-8")
    return 0 if s["status"] in ("READY_TO_SUBMIT", "DRY_RUN_OK", "HISTORICAL_OK") else 2


if __name__ == "__main__":
    raise SystemExit(main())
