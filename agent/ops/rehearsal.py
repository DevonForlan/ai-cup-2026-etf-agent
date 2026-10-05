"""Multi-day full dress rehearsal (Round 06): the COMPLETE operational pipeline, day after day.

  python agent\\ops\\rehearsal.py --start-date 2026-08-28 --days 24 --team-id TEAM_REHEARSAL --mode replay
  python agent\\ops\\rehearsal.py --start-date 2026-08-28 --end-date 2026-10-02 --mode clock-sim

Each trading day T:
  T-1 data (store; replay = what the store held before T, no network) -> previous settlement (rehearsal ledger)
  -> refresh (data_health) -> reconcile (internal vs operator-entered official) -> preflight -> Quant v1
  -> D-Plan -> validation -> package -> FINAL_CANDIDATE -> archive -> [clock-sim: receipt -> SUBMISSION_CONFIRMED]
  -> settlement of T (internal) -> official entry (double entry A/B, confirmed) -> EOD report -> T+1.
Day T's settlement must be day T+1's starting point (holdings, cash, NAV, dividends, agent_state).

Modes
  replay     competition_day mode "historical" (decision time = T 07:00 like the research simulator), so the
             NAV path must equal the research baseline exactly.
  clock-sim  competition_day mode "competition" at a simulated T-1 20:00 clock: competition gates (clean git,
             confirmed official settlement, submission window, freeze) are all active; decision data as of
             T-1 20:00 (US close of T-1 not yet visible).
All outputs live under rehearsal/<id>/ (logs/ops, submissions, archive, data/settlement, reports, audit) and are
marked REHEARSAL — never uploaded.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
import time
import traceback
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.engine.rules import load_rulebook  # noqa: E402
from agent.ops.common import TPE, Clock, load_ops_config, sha256_file, sha256_json, write_json, ymd  # noqa: E402
from agent.sim.calendar import TradingCalendar  # noqa: E402

CSV_COLS = ["date", "status", "data_health", "reconciliation", "preflight", "holdings", "cash_pct", "active_share_min",
            "orders", "warnings", "validation", "final_candidate", "archive", "runtime_total", "data_refresh_sec",
            "quant_sec", "narrative_sec", "package_sec", "fallback_level", "settlement_match", "continuity",
            "baseline_nav_match", "submission_state", "decision_fingerprint", "nav", "problems"]


def rehearsal_ops_cfg(root: Path, base: dict | None = None) -> dict:
    c = copy.deepcopy(base or load_ops_config())
    rel = {"settlement_dir": "data/settlement", "submissions_dir": "submissions", "archive_dir": "archive",
           "ops_logs_dir": "logs/ops", "etf_snapshots_dir": "data/raw/active_etf",
           "first_seen_ledger": "data/observations/mops_revenue_first_seen.parquet", "ops_reports_dir": "reports/ops_daily"}
    for k in c["paths"]:
        c["paths"][k] = str(root / rel.get(k, k))
    return c


def official_from_internal(s) -> dict:
    return {"date": s.date, "holdings": dict(s.holdings), "cash": str(s.cash), "nav": str(s.nav),
            "accrued_dividends": str(s.accrued_dividends), "warnings": [w["rule"] for w in s.warnings]}


def write_entry_csv(off: dict, path: Path) -> Path:
    rows = ["ticker,shares"] + [f"{t},{n}" for t, n in sorted(off["holdings"].items())]
    rows += [f"__DATE__,{off['date']}", f"__CASH__,{off['cash']}", f"__NAV__,{off['nav']}",
             f"__ACCRUED__,{off['accrued_dividends']}", f"__WARNINGS__,{';'.join(off['warnings'])}"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def continuity_problems(prev_settlement, start: dict | None, prev_start: dict | None, trade_date: str) -> list[str]:
    """Day T's settlement vs the starting point competition_day used for T+1."""
    if prev_settlement is None:
        return []
    if not start:
        return ["no starting settlement recorded"]
    p = []
    if start["date"] != prev_settlement.date:
        p.append(f"start date {start['date']} != settlement {prev_settlement.date}")
    if start["holdings"] != prev_settlement.holdings:
        p.append("holdings break")
    if Decimal(start["cash"]) != prev_settlement.cash:
        p.append("cash break")
    if Decimal(start["nav"]) != prev_settlement.nav:
        p.append("NAV break")
    if Decimal(start["accrued_dividends"]) != prev_settlement.accrued_dividends:
        p.append("accrued dividend break")
    if start["agent_state_hash"] != sha256_json(prev_settlement.agent_state or {}):
        p.append("agent_state break")
    if start.get("warning_count") != prev_settlement.warning_count:
        p.append("warning count break")
    st = prev_settlement.agent_state or {}
    ed = st.get("entry_date", {})
    for t in prev_settlement.holdings:
        if t not in ed:
            p.append(f"no entry_date for held {t}")
        elif ed[t] > prev_settlement.date:
            p.append(f"entry_date {ed[t]} after settlement for {t}")
    if prev_start and prev_start.get("agent_state_day_index") is not None and \
            st.get("day_index") is not None and st["day_index"] < prev_start["agent_state_day_index"]:
        p.append("day_index went backwards")
    if int(st.get("last_rebalance_index") or 0) > int(st.get("day_index") or 0):
        p.append("last_rebalance_index > day_index")
    return p


def rehearse(start_date: str, *, end_date: str | None = None, days: int | None = None, team_id: str = "TEAM_REHEARSAL",
             mode: str = "replay", strategy: str = "config/strategy_quant_v1.yaml", root: Path | None = None,
             store: HistoryStore | None = None, baseline_run: str | None = None, git: dict | None = None,
             store_is_fixture: bool = False, record_receipts: bool = True, quiet: bool = False) -> dict:
    from agent.competition_day import run_competition_day
    from agent.ops.archive_run import partial_dirs, verify_archive
    from agent.ops.daily_reports import write_eod_report
    from agent.ops.package_submission import active_final, verify_package
    from agent.ops.reconcile import reconcile
    from agent.ops.refresh_daily import replay_fetchers
    from agent.ops.settle_internal import settle_day
    from agent.ops.settlement import load_internal
    from agent.ops.settlement_entry import import_settlement
    store = store or HistoryStore()
    rb = load_rulebook()
    rid = f"{mode}_{start_date.replace('-', '')}_{datetime.now(TPE):%Y%m%d_%H%M%S}"
    root = root or ROOT / "rehearsal" / rid
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.txt").write_text("REHEARSAL OUTPUT — NOT FOR UPLOAD. Generated by agent/ops/rehearsal.py\n",
                                     encoding="utf-8")
    ops_cfg = rehearsal_ops_cfg(root)
    overrides = {}
    if mode == "replay":
        # historical ETF holdings exist only from 2026-10 for latest-only issuers: freshness cannot be judged
        ops_cfg["preflight"]["etf_stale_days_block"] = 99999
        overrides["preflight.etf_stale_days_block"] = "99999 (historical ETF history unavailable; still reported as WARN)"
    write_json(root / "rehearsal_config.json", {"mode": mode, "start": start_date, "end": end_date, "days": days,
                                                 "team_id": team_id, "strategy": strategy, "overrides": overrides,
                                                 "strategy_sha256": sha256_file(ROOT / strategy)})
    cal = TradingCalendar(store.dates("daily_prices"))
    all_days = [d for d in cal.days if d >= start_date and (end_date is None or d <= end_date)]
    tdays = all_days[:days] if days else all_days
    base = Path(baseline_run) if baseline_run else None
    rows, prev_settlement, prev_start, run_ids, fail_days = [], None, None, [], []
    t_all = time.perf_counter()
    for i, T in enumerate(tdays):
        prev_cal = cal.prev(T)
        clock = Clock(f"{prev_cal}T20:00:00+08:00")
        cd_mode = "historical" if mode == "replay" else "competition"
        probs, row = [], {"date": T}
        try:
            s = run_competition_day(T, team_id, cd_mode, config=strategy, clock=clock, ops_cfg=ops_cfg, store=store,
                                    refresh_fetchers=replay_fetchers(), initial=(i == 0), git=git,
                                    store_is_fixture=store_is_fixture, archive_readonly=True,
                                    operator="rehearsal-agent")
            ok_status = s["status"] in ("HISTORICAL_OK", "READY_TO_SUBMIT", "DRY_RUN_OK")
            if not ok_status:
                probs.append(f"status {s['status']}: {s.get('reason')}")
            probs += continuity_problems(prev_settlement, s.get("start"), prev_start, T)
            fin = active_final(T, ops_cfg)
            pkg = Path(s["package"]) if s.get("package") else None
            arch = Path(s["archive"]) if s.get("archive") else None
            if fin is None:
                probs.append("missing FINAL_CANDIDATE")
            else:
                ffile = Path(ops_cfg["paths"]["submissions_dir"]) / ymd(T) / "FINAL" / fin["file"]
                fdoc = json.loads(ffile.read_text(encoding="utf-8")) if ffile.exists() else {}
                if not ffile.exists() or sha256_file(ffile) != fin["sha256"]:
                    probs.append("FINAL hash mismatch")
                if fdoc.get("trade_date") != T:
                    probs.append("wrong-date FINAL")
                if fdoc.get("team_id") != team_id:
                    probs.append("wrong-team FINAL")
            if pkg is None or verify_package(pkg):
                probs.append(f"package problems {verify_package(pkg) if pkg else 'missing'}")
            if arch is None or verify_archive(arch):
                probs.append("archive problems")
            elif arch.name in run_ids:
                probs.append("archive collision")
            else:
                run_ids.append(arch.name)
            if s.get("fallback"):
                probs.append("unexpected fallback")
            if s.get("validation") != "PASS":
                probs.append("invalid D-Plan")
            sub_state = s.get("submission_state")
            if mode == "clock-sim" and record_receipts and fin is not None:
                from agent.submission.receipt import Receipt, record_receipt
                st = record_receipt(Receipt(T, team_id, fin["sha256"], clock.now().isoformat(), "other",
                                            "rehearsal-agent", f"REHEARSAL-{ymd(T)}", "accepted", None,
                                            "simulated receipt (rehearsal; nothing was uploaded)"), ops_cfg)
                sub_state = st["state"]
                if sub_state != "SUBMISSION_CONFIRMED":
                    probs.append(f"submission state {sub_state}")
            # ---- evening of T: internal settlement, operator official entry (double entry), EOD
            sett = settle_day(T, store=store, ops_cfg=ops_cfg, initial_cash=rb.rules.initial_cash if i == 0 else None)
            off = official_from_internal(sett)
            closes = {r.ticker: float(r.close) for r in store.load("daily_prices").query("date == @T").itertuples()}
            ent_dir = root / "operator_entry" / ymd(T)
            a = write_entry_csv(off, ent_dir / "official_A.csv")
            b = write_entry_csv(off, ent_dir / "official_B.csv")
            ent = import_settlement(T, a, verify_file=b, operator="rehearsal operator",
                                    source="rehearsal: copied from internal ledger (no official platform)",
                                    snapshot_ref=None, confirm=True, ops_cfg=ops_cfg, closes=closes)
            if ent["status"] != "DOUBLE_ENTRY_MATCH":
                probs.append(f"official entry {ent['status']}: {ent['problems'][:3]}")
            sm = reconcile({"holdings": sett.holdings, "cash": str(sett.cash), "nav": str(sett.nav),
                            "accrued_dividends": str(sett.accrued_dividends),
                            "warnings": [w["rule"] for w in sett.warnings]}, off, ops_cfg)["status"]
            calc_nav = sum(Decimal(n) * Decimal(str(closes[t])) for t, n in sett.holdings.items()) + sett.cash
            if abs(calc_nav - sett.nav) > Decimal("0.01"):
                probs.append("settlement NAV != sum(shares x close) + cash")
            if sett.agent_state.get("day_index") is None:
                probs.append("agent_state.day_index missing")
            nxt = all_days[i + 1] if i + 1 < len(all_days) else None
            write_eod_report(T, sett, ops_cfg=ops_cfg, next_date=nxt)
            base_match = ""
            if base and (base / "settlement" / f"{T}.json").exists():
                bj = json.loads((base / "settlement" / f"{T}.json").read_text(encoding="utf-8"))
                base_match = str(Decimal(bj["nav"]) == sett.nav)
                if base_match != "True":
                    probs.append(f"NAV {sett.nav} != baseline {bj['nav']}")
            reloaded = load_internal(T, ops_cfg)
            if reloaded is None or reloaded.nav != sett.nav:
                probs.append("settlement ledger reload mismatch")
            du = s.get("durations", {})
            row.update({
                "status": s["status"], "data_health": s.get("data_health"),
                "reconciliation": (s.get("settlement") or {}).get("reconciliation", "INITIAL" if i == 0 else "-"),
                "preflight": (s.get("preflight") or {}).get("level"), "holdings": len(sett.holdings),
                "cash_pct": round(float(sett.cash / sett.nav), 6), "active_share_min": s.get("active_share_min"),
                "orders": s.get("orders"), "warnings": len(sett.warnings), "validation": s.get("validation"),
                "final_candidate": fin["sha256"][:23] if fin else "", "archive": arch.name if arch else "",
                "runtime_total": s.get("total_sec"), "data_refresh_sec": du.get("data_refresh"),
                "quant_sec": round(sum(du.get(f"run_day.{k}", 0) for k in ("data_features", "ranking", "portfolio")), 3),
                "narrative_sec": du.get("run_day.dplan"), "package_sec": du.get("package"),
                "fallback_level": s.get("degradation_level"), "settlement_match": sm,
                "continuity": "OK" if not [x for x in probs if "break" in x or "entry_date" in x] else "BREAK",
                "baseline_nav_match": base_match, "submission_state": sub_state,
                "decision_fingerprint": (s.get("decision_fingerprint") or "")[:23], "nav": str(sett.nav)})
            prev_start = {"agent_state_day_index": (sett.agent_state or {}).get("day_index")}
            prev_settlement = sett
        except Exception as e:  # noqa: BLE001
            probs.append(f"UNHANDLED {type(e).__name__}: {e}")
            (root / "errors").mkdir(exist_ok=True)
            (root / "errors" / f"{ymd(T)}.txt").write_text(traceback.format_exc(), encoding="utf-8")
        row["problems"] = "; ".join(probs)
        row.setdefault("status", "EXCEPTION")
        rows.append(row)
        if probs:
            fail_days.append(T)
        if not quiet:
            print(f"{T} {row.get('status'):15s} nav={row.get('nav', '-'):>32s} orders={row.get('orders')} "
                  f"rec={row.get('reconciliation')} {'OK' if not probs else 'PROBLEMS: ' + row['problems'][:150]}",
                  flush=True)
        if any(x.startswith("UNHANDLED") for x in probs):
            break
    with open(root / "rehearsal_daily.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        w.writerows(rows)
    from agent.ops.audit import build_audit
    build_audit(root / "audit", ops_cfg)
    rt = sorted(float(r["runtime_total"]) for r in rows if r.get("runtime_total") not in (None, ""))
    crit = {
        "operational_pass": f"{sum(1 for r in rows if not r['problems'])}/{len(tdays)}",
        "invalid_dplan": sum(1 for r in rows if r.get("validation") not in ("PASS",)),
        "unexpected_fallback": sum(1 for r in rows if "unexpected fallback" in r["problems"]),
        "accidental_overwrite": sum(1 for r in rows if "collision" in r["problems"] or "overwrite" in r["problems"]),
        "wrong_date_package": sum(1 for r in rows if "wrong-date" in r["problems"]),
        "wrong_team_package": sum(1 for r in rows if "wrong-team" in r["problems"]),
        "archive_collision": sum(1 for r in rows if "archive collision" in r["problems"]),
        "settlement_continuity_break": sum(1 for r in rows if r.get("continuity") == "BREAK"),
        "missing_final_candidate": sum(1 for r in rows if "missing FINAL" in r["problems"]),
        "hash_mismatch": sum(1 for r in rows if "hash mismatch" in r["problems"]),
        "unhandled_exception": sum(1 for r in rows if "UNHANDLED" in r["problems"]),
        "partial_leftovers": len(partial_dirs(ops_cfg)),
    }
    summ = {"rehearsal_id": root.name, "root": str(root), "mode": mode, "team_id": team_id, "days": len(rows),
            "planned_days": len(tdays), "first": tdays[0] if tdays else None, "last": tdays[-1] if tdays else None,
            "final_nav": rows[-1].get("nav") if rows else None, "criteria": crit, "fail_days": fail_days,
            "passed": not fail_days and len(rows) == len(tdays) and not crit["partial_leftovers"],
            "runtime_p50": rt[len(rt) // 2] if rt else None, "runtime_p95": rt[min(len(rt) - 1, int(0.95 * len(rt)))] if rt else None,
            "total_sec": round(time.perf_counter() - t_all, 1), "overrides": overrides,
            "baseline_run": baseline_run}
    write_json(root / "rehearsal_summary.json", summ)
    return summ


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", required=True)
    ap.add_argument("--end-date", default=None)
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--team-id", default="TEAM_REHEARSAL")
    ap.add_argument("--mode", choices=["replay", "clock-sim"], default="replay")
    ap.add_argument("--strategy", default="config/strategy_quant_v1.yaml")
    ap.add_argument("--baseline-run", default=None, help="research sim run dir to compare NAV per day (replay mode)")
    a = ap.parse_args(argv)
    s = rehearse(a.start_date, end_date=a.end_date, days=a.days, team_id=a.team_id, mode=a.mode,
                 strategy=a.strategy, baseline_run=a.baseline_run)
    print(json.dumps(s, indent=1, ensure_ascii=False))
    return 0 if s["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
