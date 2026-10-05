"""One-command daily run. Produces a READY_TO_SUBMIT package and a FINAL_CANDIDATE marker.
It NEVER uploads, logs in, automates a browser or calls any official endpoint (NC-1 unconfirmed).

  python agent\\competition_day.py --date 2026-10-27 --team-id TEAM_TEST --mode dry-run
  python agent\\competition_day.py --date 2026-10-02 --team-id TEAM_TEST --mode historical --replay-run sim_runs\\round05_baseline_quant_v1
  python agent\\competition_day.py --date 2026-10-27 --team-id TEAM_042 --mode competition [--llm-config config\\llm_narrative_v1.yaml]

Flow: DEADLINE GUARD -> DATA REFRESH -> SETTLEMENT + RECONCILIATION -> PREFLIGHT -> PIT SNAPSHOT ->
QUANT CORE v1 -> PORTFOLIO -> COMPLIANCE -> ORDERS -> NARRATIVE -> D-PLAN -> VALIDATION ->
SUBMISSION PACKAGE -> FINAL_CANDIDATE (freeze) -> ARCHIVE -> OPERATOR SUMMARY / REPORT.

Safe degradation: L0 quant + approved real-LLM narrative | L1 quant + template narrative |
L2 quant with cached/stale non-critical data | L3 deterministic fallback (previous legal portfolio).
Every level must pass the competition validator; otherwise status = BLOCKED and no FINAL_CANDIDATE.
A FINAL_CANDIDATE, once marked, is frozen: later runs produce candidates only (agent/ops/final.py replace-final).
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

from agent.config import D, load_strategy  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.engine.rules import load_rulebook  # noqa: E402
from agent.ops import deadline as DL  # noqa: E402
from agent.ops.archive_run import archive_run, run_id_for  # noqa: E402
from agent.ops.common import (BLOCK, PASS, TPE, WARN, Check, Clock, load_ops_config, ops_logger,  # noqa: E402
                              ops_path, sha256_json, write_json, ymd)
from agent.ops.fingerprint import decision_core_hash, decision_fingerprint, store_snapshot_hash  # noqa: E402
from agent.ops.package_submission import active_final, build_package, mark_final  # noqa: E402
from agent.ops.preflight import config_hashes, git_info, prompt_versions, run_preflight  # noqa: E402
from agent.ops.reconcile import reconcile  # noqa: E402
from agent.ops.settlement import (ManualFileSettlementProvider, ReplaySettlementProvider, apply_official,  # noqa: E402
                                  load_internal, path_for)
from agent.pipeline import code_version, llm_settings, run_day  # noqa: E402
from agent.sim.calendar import TradingCalendar  # noqa: E402
from agent.sim.models import Settlement  # noqa: E402

OK_STATUSES = ("READY_TO_SUBMIT", "DRY_RUN_OK", "HISTORICAL_OK")


class SimulatedCrash(BaseException):
    """Test-only: emulates a process crash (not caught by `except Exception`)."""


def _closes_on(store: HistoryStore, d: str) -> dict:
    p = store.load("daily_prices")
    p = p[p["date"] == d]
    return {r.ticker: D(round(float(r.close), 4)) for r in p.itertuples() if r.close == r.close}


def settlement_hash(s: Settlement) -> str:
    return sha256_json({"holdings": s.holdings, "cash": str(s.cash), "nav": str(s.nav)})


def http_reference_time(url: str = "https://www.twse.com.tw/", timeout: float = 5.0) -> datetime | None:
    """Best-effort reference clock from a public server's HTTP Date header (no login, read-only HEAD)."""
    try:
        import email.utils
        import requests
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        return email.utils.parsedate_to_datetime(r.headers["Date"]).astimezone(TPE)
    except Exception:  # noqa: BLE001
        return None


def clock_skew_check(now: datetime, ref: datetime | None, ops_cfg: dict, competition: bool) -> Check:
    if ref is None:
        return Check("clock_skew", PASS, "not measured (no reference time)")
    skew = abs((now - ref).total_seconds())
    warn_s = float(ops_cfg["preflight"].get("max_clock_skew_sec", 120))
    block_s = float(ops_cfg["preflight"].get("block_clock_skew_sec", 600))
    lvl = BLOCK if (skew > block_s and competition) else (WARN if skew > warn_s else PASS)
    return Check("clock_skew", lvl, f"system clock vs reference: {skew:.0f}s (warn > {warn_s:.0f}s, block > {block_s:.0f}s)")


def sla_check(durations: dict, ops_cfg: dict) -> list[dict]:
    sla = ops_cfg.get("sla") or {}
    m = {"quant_sec": durations.get("run_day.total", 0) - durations.get("run_day.validation", 0),
         "validation_sec": durations.get("run_day.validation", 0), "package_sec": durations.get("package", 0),
         "archive_sec": durations.get("archive", 0), "data_refresh_sec": durations.get("data_refresh", 0)}
    return [{"metric": k, "value": round(v, 2), "limit": sla[k], "breach": v > sla[k]} for k, v in m.items() if k in sla]


def run_competition_day(trade_date: str, team_id: str, mode: str = "dry-run", *,
                        config: str = "config/strategy_quant_v1.yaml", llm_config: str | None = None,
                        clock: Clock | None = None, ops_cfg: dict | None = None, store: HistoryStore | None = None,
                        refresh_fetchers: dict | None = None, skip_refresh: bool = False,
                        settlement_provider=None, initial: bool = False, replay_run: str | None = None,
                        data_faults: set | None = None, git: dict | None = None, llm_provider=None,
                        archive_readonly: bool = True, store_is_fixture: bool = False,
                        reference_time: datetime | None = None, crash_hook=None, operator: str = "agent",
                        write_report: bool = True) -> dict:
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
        try:
            from agent.submission.base import get_state
            summary["submission_state"] = get_state(trade_date, ops_cfg)["state"]
        except Exception:  # noqa: BLE001
            summary["submission_state"] = "UNKNOWN"
        write_json(ops_path(ops_cfg, "ops_logs_dir") / ymd(trade_date) / "competition_day_summary.json", summary)
        lg.info(f"STATUS {status} {json.dumps({k: summary.get(k) for k in ('final_file', 'sha256', 'reason')}, ensure_ascii=False)}")
        if write_report:
            try:
                from agent.ops.daily_reports import write_operator_report
                summary["operator_report"] = str(write_operator_report(summary, ops_cfg))
            except Exception as e:  # noqa: BLE001
                lg.error(f"operator report failed: {e}")
        return summary

    def hook(name):
        if crash_hook:
            crash_hook(name)

    # ---------------------------------------------------------------- deadline
    dls = DL.status(trade_date, clock, ops_cfg)
    summary["deadline"] = dls.to_dict()
    lg.info(f"deadline phase {dls.phase} ({dls.minutes_left:.1f} min left)")
    # ---------------------------------------------------------------- data refresh
    t0 = time.perf_counter()
    data_health = None
    want_refresh = (mode != "historical" or refresh_fetchers is not None) and not skip_refresh
    if want_refresh and dls.allow_refresh:
        from agent.ops.refresh_daily import refresh
        data_health = refresh(trade_date, store=store, fetchers=refresh_fetchers, ops_cfg=ops_cfg, clock=clock,
                              allow_noncritical=dls.allow_noncritical_refresh)
        store._cache.clear()
    elif want_refresh or mode != "historical":
        notes.append(f"data refresh skipped ({'deadline ' + dls.phase if not dls.allow_refresh else 'requested'})")
    durations["data_refresh"] = round(time.perf_counter() - t0, 2)
    hook("after_refresh")
    # ---------------------------------------------------------------- settlement + reconciliation
    t0 = time.perf_counter()
    cal = TradingCalendar(store.dates("daily_prices") + [trade_date])
    prev_date = cal.prev(trade_date)
    sstat = {"previous_date": prev_date, "initial_day": initial}
    rec = None
    start: Settlement | None = None
    extra_checks: list[Check] = []
    if initial:
        start = Settlement.initial(prev_date or "initial", rb.rules.initial_cash)
        sstat.update(previous_available=True, source="initial cash")
    else:
        replay = ReplaySettlementProvider(Path(replay_run), ops_cfg) if replay_run else None
        internal = load_internal(prev_date, ops_cfg) or (replay.settlement(prev_date) if replay else None)
        provider = settlement_provider or (replay if (replay and mode != "competition") else
                                           ManualFileSettlementProvider(ops_cfg))
        official = provider.get(prev_date) if provider else None
        if official is not None and isinstance(provider, ManualFileSettlementProvider):
            from agent.ops.settlement_entry import confirmation_status
            cs = confirmation_status(prev_date, ops_cfg)
            sstat["confirmation"] = cs
            lvl = PASS if cs["confirmed"] else (BLOCK if mode == "competition" else WARN)
            extra_checks.append(Check("settlement_confirmed", lvl, f"{prev_date}: {cs['detail']}"
                                      + (f" ({cs.get('double_entry')})" if cs.get("double_entry") else "")))
        if internal is not None and official is not None:
            idict = {"holdings": internal.holdings, "cash": str(internal.cash), "nav": str(internal.nav),
                     "accrued_dividends": str(internal.accrued_dividends),
                     "warnings": [w["rule"] for w in internal.warnings]}
            rec = reconcile(idict, official, ops_cfg)
            rec["date"] = prev_date
            write_json(path_for(prev_date, "reconciliation", ops_cfg), rec)
            rl = ops_logger(trade_date, "reconciliation", ops_cfg)
            rl.info(f"{prev_date} {rec['status']} source={official.get('source')} -> {rec['action']}")
            for d in rec["diffs"]:
                rl.info(f"  diff {json.dumps(d, ensure_ascii=False)}")
            sstat["reconciliation"] = rec["status"]
            if rec["status"] != "BLOCK":
                start = apply_official(internal, official)
                sstat.update(previous_available=True, source=f"official ({official.get('source')}) + internal state")
            else:                       # both exist but disagree: a human decides, the agent never picks a side
                sstat.update(previous_available=True, source="internal and official DISAGREE (see reconciliation)")
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
    if start is not None:
        summary["start"] = {"date": start.date, "holdings": dict(start.holdings), "cash": str(start.cash),
                            "nav": str(start.nav), "accrued_dividends": str(start.accrued_dividends),
                            "settlement_hash": settlement_hash(start),
                            "agent_state_hash": sha256_json(start.agent_state or {}),
                            "warning_count": start.warning_count}
    summary["settlement"] = sstat
    summary["reconciliation"] = rec
    durations["settlement"] = round(time.perf_counter() - t0, 2)
    # ---------------------------------------------------------------- preflight
    t0 = time.perf_counter()
    if reference_time is None and mode == "competition" and clock.fixed is None:   # real clock only
        reference_time = http_reference_time()
    extra_checks.append(clock_skew_check(clock.now(), reference_time, ops_cfg, mode == "competition"))
    closes_prev = _closes_on(store, prev_date) if prev_date else {}
    pf = run_preflight(trade_date, mode="competition" if mode == "competition" else "dry-run", strategy_cfg=config,
                       llm_cfg=llm_config, clock=clock, ops_cfg=ops_cfg, data_health=data_health,
                       settlement_status=sstat, prev_holdings=start.holdings if start else None,
                       prev_cash=start.cash if start else None, closes_prev=closes_prev, git=git, store=store,
                       extra=extra_checks)
    summary["preflight"] = {"level": pf["level"], "blocks": [c for c in pf["checks"] if c["level"] == BLOCK],
                            "warns": [c["name"] for c in pf["checks"] if c["level"] == "WARN"]}
    summary["data_health"] = (data_health or {}).get("level", "NOT_RUN")
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
                    llm=llm, as_of_override=as_of, data_faults=data_faults, store_is_fixture=store_is_fixture)
    except Exception as e:  # noqa: BLE001
        lg.error(traceback.format_exc())
        return finish("BLOCKED", reason=f"program error in run_day: {type(e).__name__}: {e}"[:400])
    durations["quant_dplan_validation"] = round(time.perf_counter() - t0, 2)
    vl = ops_logger(trade_date, "validation", ops_cfg)
    vl.info(f"{r.dplan_path.name if r.dplan_path else None} ok={r.validation.ok} {r.validation.summary()} "
            f"fallback={r.fallback}")
    for c_ in r.validation.to_dict()["checks"]:
        if c_["status"] not in ("PASS", "NOT_APPLICABLE"):
            vl.info(f"  {c_['status']} {c_['rule_id']}: {str(c_['message'])[:200]}")
    durations.update({f"run_day.{k}": round(v, 3) for k, v in r.timings.items()})
    degraded_data = bool(data_health and data_health["level"] != "PASS")
    level = 3 if r.fallback else (0 if r.narrative_used_llm else (2 if degraded_data else 1))
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
    if not r.validation.ok and dls.phase == "PAST_CUTOFF" and mode != "historical":
        return finish("LATE_PAST_CUTOFF", reason="past submission cutoff (validator rejects late timestamps); "
                                                 "no package / FINAL produced")
    if not r.validation.ok:
        return finish("BLOCKED", reason="D-Plan validation FAIL even after deterministic fallback "
                                        "(previous portfolio may be illegal: see EMERGENCY_RUNBOOK)")
    hook("before_package")
    # ---------------------------------------------------------------- package + final + archive
    t0 = time.perf_counter()
    g = git or git_info()
    gsha = code_version()
    run_id = run_id_for(clock.now(), gsha)
    chash = config_hashes(config, llm_config)
    data_hash = (data_health or {}).get("store_manifest_hash") or store_snapshot_hash(store.root)
    shash = settlement_hash(start)
    fp = decision_fingerprint(r.doc, strategy_hash=chash.get("strategy"), data_snapshot_hash=data_hash,
                              settlement_hash=shash, code_version=gsha)
    meta = {"trade_date": trade_date, "generated_at": clock.now().isoformat(), "git_sha": gsha,
            "git_dirty": bool(g["dirty_paths"]), "python_version": platform.python_version(),
            "config_hashes": chash, "prompt_versions": prompt_versions(),
            "data_snapshot_hash": data_hash, "settlement_hash": shash,
            "decision_core_hash": decision_core_hash(r.doc), "decision_fingerprint": fp,
            "provider": (llm["cfg"].get("provider") if llm else "template"),
            "model": (llm["cfg"].get("model") if llm else None),
            "llm_replay_id": f"logs/llm/{ymd(trade_date)}/calls.jsonl" if llm else None,
            "degradation_level": level, "deadline": dls.to_dict(), "run_durations": durations}
    summary["decision_fingerprint"] = fp
    pkg = build_package(r, team_id=team_id, trade_date=trade_date, run_id=run_id, mode=mode,
                        data_health=data_health, reconciliation=rec, preflight=pf, run_metadata=meta, ops_cfg=ops_cfg,
                        extra_json={"agent_state.json": r.agent_state}, crash_hook=crash_hook)
    late = dls.phase == "PAST_CUTOFF" and mode != "historical"
    if late:
        fin = {"ok": False, "reasons": ["past submission cutoff: candidate kept, NOT promoted to FINAL"]}
    else:
        fin = mark_final(pkg, team_id=team_id, trade_date=trade_date, mode=mode, ops_cfg=ops_cfg, operator=operator,
                         cutoff=dls.cutoff.isoformat())
    durations["package"] = round(time.perf_counter() - t0, 2)
    final_action, compare_res = None, None
    if fin.get("ok"):
        final_action = "MARKED"
    elif fin.get("kept"):
        from agent.ops.compare_candidates import compare
        cur = fin["existing"]
        compare_res = compare(pkg.parent / cur["run_id"], pkg)
        final_action = "KEPT_IDENTICAL" if compare_res["same_decision"] else "KEPT_DIFFERENT"
        notes.append(f"FINAL already frozen ({cur['run_id']}); new candidate vs FINAL: {compare_res['class']}"
                     + (f" — {compare_res['reason']}" if compare_res["reason"] else "")
                     + ("" if compare_res["same_decision"] else " -> review; switch only with final.py replace-final"))
    hook("before_archive")
    t0 = time.perf_counter()
    arch = archive_run(trade_date, run_id, package_dir=pkg, ops_cfg=ops_cfg, readonly=archive_readonly,
                       config_files=[config, "config/competition.yaml", "config/unconfirmed_rules.yaml",
                                     "config/ops.yaml"] + ([llm_config] if llm_config else []), crash_hook=crash_hook)
    durations["archive"] = round(time.perf_counter() - t0, 2)
    summary["sla"] = sla_check(durations, ops_cfg)
    summary["final_action"] = final_action
    if compare_res:
        summary["final_comparison"] = {"class": compare_res["class"], "reason": compare_res["reason"]}
    if late:
        return finish("LATE_PAST_CUTOFF", reason=fin["reasons"][0], package=str(pkg), archive=str(arch), run_id=run_id)
    if not fin.get("ok") and not fin.get("kept"):
        return finish("BLOCKED", reason="FINAL_CANDIDATE refused: " + "; ".join(fin["reasons"]),
                      package=str(pkg), archive=str(arch), run_id=run_id)
    if mode == "competition":
        from agent.submission.manual import ManualSubmissionProvider
        prep = ManualSubmissionProvider(ops_cfg).prepare(trade_date, team_id)
        if not prep["ok"]:
            notes.append("submission prepare: " + "; ".join(prep["problems"]))
    act = active_final(trade_date, ops_cfg)
    if act is None or act["team_id"] != team_id or act["trade_date"] != trade_date:
        return finish("BLOCKED", reason=f"active FINAL does not match team {team_id} / date {trade_date}",
                      package=str(pkg), archive=str(arch), run_id=run_id)
    status ="READY_TO_SUBMIT" if mode == "competition" else ("DRY_RUN_OK" if mode == "dry-run" else "HISTORICAL_OK")
    return finish(status, final_file=act["path"], sha256=act["sha256"], final_run_id=act["run_id"],
                  package=str(pkg), archive=str(arch), run_id=run_id)


def operator_summary(s: dict) -> str:
    """Console summary; the decisive facts are always the LAST 15 lines (human-error defence)."""
    L = "=" * 72
    p = s.get("portfolio", {})
    d = s.get("deadline", {})
    body = [L, f" TRADE DATE  : {s['trade_date']}     TEAM: {s['team_id']}     MODE: {s['mode'].upper()}",
            f" DEADLINE    : {d.get('phase')}  ({d.get('minutes_left')} min left)",
            f" DATA        : health={s.get('data_health', '-')}  preflight={(s.get('preflight') or {}).get('level', '-')}"
            f"  warns={(s.get('preflight') or {}).get('warns', [])[:6]}",
            f" SETTLEMENT  : {s.get('settlement', {}).get('source', '-')}  reconciliation={s.get('settlement', {}).get('reconciliation', '-')}",
            f" PORTFOLIO   : regime={p.get('regime', '-')} posture={(p.get('posture') or {}).get('net_exposure_intent', '-')}"
            f"  holdings={p.get('holdings_after', '-')}  cash={p.get('cash_ratio_est', 0):.2%}",
            f" ACTIVE SHARE: {s.get('active_share_min')}",
            f" ORDERS      : {s.get('orders', '-')}  (decisions {s.get('decisions', '-')})",
            f" D-PLAN      : degradation L{s.get('degradation_level', '-')}  fallback={s.get('fallback', '-')}  "
            f"validation={s.get('validation', '-')} {s.get('validation_summary', '')}",
            f" LLM         : {s.get('llm', {})}",
            f" FINAL ACTION: {s.get('final_action')}  {s.get('final_comparison') or ''}",
            f" ARCHIVE     : {s.get('archive', '-')}",
            f" RUNTIME     : {s.get('total_sec')} s   SLA breaches: {[x['metric'] for x in s.get('sla', []) if x['breach']]}"]
    for n in s.get("notes", [])[:6]:
        body.append(f" NOTE        : {n}")
    ready = s["status"] == "READY_TO_SUBMIT"
    comp = s["mode"] == "competition"
    big = f"#####  {s['trade_date']}  #####  {s['team_id']}  #####  {'COMPETITION' if comp else 'DRY RUN — DO NOT UPLOAD'}  #####"
    tail = [L, big, L,
            f" RUN STATUS  : {s['status']}" + (f"   ({str(s.get('reason'))[:160]})" if s.get("reason") else ""),
            f" READY       : {'READY TO SUBMIT' if ready else 'NOT READY — DO NOT UPLOAD'}",
            f" MODE        : {s['mode'].upper()}",
            f" TEAM ID     : {s['team_id']}",
            f" TRADE DATE  : {s['trade_date']}",
            f" FINAL FILE  : {s.get('final_file', '-- NONE --')}",
            f" SHA256      : {s.get('sha256', '-')}",
            f" CUT-OFF     : {d.get('cutoff', '-')}  ({d.get('minutes_left')} min left)",
            f" SUBMISSION  : {s.get('submission_state', '-')}  (file generated != submitted; record the receipt)",
            L]
    return "\n".join(body + tail)


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
    ap.add_argument("--offline", action="store_true", help="no network: every source from store probes only")
    ap.add_argument("--initial", action="store_true", help="first competition day: start from initial cash")
    ap.add_argument("--replay-run", default=None, help="sim run dir used as settlement source (non-competition)")
    a = ap.parse_args(argv)
    if a.mode == "competition" and a.replay_run:
        print("--replay-run is not allowed in competition mode")
        return 2
    fetchers = None
    if a.offline:
        from agent.ops.refresh_daily import offline_fetchers
        fetchers = offline_fetchers()
    s = run_competition_day(a.date, a.team_id, a.mode, config=a.config, llm_config=a.llm_config,
                            clock=Clock(a.clock) if a.clock else None, skip_refresh=a.skip_refresh,
                            initial=a.initial, replay_run=a.replay_run, refresh_fetchers=fetchers)
    txt = operator_summary(s)
    print(txt)
    (ops_path(load_ops_config(), "ops_logs_dir") / ymd(a.date) / "operator_summary.txt").write_text(txt, encoding="utf-8")
    return 0 if s["status"] in OK_STATUSES else 2


if __name__ == "__main__":
    raise SystemExit(main())
