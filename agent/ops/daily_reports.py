"""Daily operator reports (Round 06): reports/ops_daily/YYYYMMDD_OPERATOR_SUMMARY.md (morning / pre-upload)
and reports/ops_daily/YYYYMMDD_EOD.md (after the trade date's settlement)."""
from __future__ import annotations

import json
from pathlib import Path

from agent.config import ROOT
from agent.ops.common import load_ops_config, ops_path, write_json, ymd


def reports_dir(ops_cfg: dict) -> Path:
    key = "ops_reports_dir"
    if key in ops_cfg.get("paths", {}):
        return ops_path(ops_cfg, key)
    return ROOT / "reports" / "ops_daily"


def write_operator_report(s: dict, ops_cfg: dict | None = None) -> Path:
    ops_cfg = ops_cfg or load_ops_config()
    p = s.get("portfolio") or {}
    st = s.get("settlement") or {}
    d = s.get("deadline") or {}
    comp = s["mode"] == "competition"
    ready = s["status"] == "READY_TO_SUBMIT"
    lines = [f"# {s['trade_date']} — {s['team_id']} — {'COMPETITION' if comp else 'DRY RUN (do not upload)'}", "",
             f"## STATUS: **{s['status']}** — {'READY TO SUBMIT' if ready else 'NOT READY / NOT FOR UPLOAD'}", ""]
    if s.get("reason"):
        lines += [f"> {s['reason']}", ""]
    rows = [
        ("Data health", s.get("data_health", "NOT_RUN")),
        ("Official settlement", f"{st.get('source', '-')} (prev {st.get('previous_date')})"),
        ("Settlement confirmation", (st.get("confirmation") or {}).get("detail", "n/a")),
        ("Reconciliation", st.get("reconciliation", "-")),
        ("Preflight", f"{(s.get('preflight') or {}).get('level')} warns={(s.get('preflight') or {}).get('warns')}"),
        ("Git / strategy", f"{(s.get('decision_fingerprint') or '')[:19]} fingerprint; see package run_metadata.json"),
        ("Portfolio", f"regime {p.get('regime')}, posture {(p.get('posture') or {}).get('net_exposure_intent')}, "
                      f"holdings {p.get('holdings_after')}"),
        ("Cash (est.)", f"{p.get('cash_ratio_est', 0):.2%}" if p else "-"),
        ("Active Share (min)", s.get("active_share_min")),
        ("Orders", f"{s.get('orders', '-')} (decisions {s.get('decisions', '-')})"),
        ("LLM", s.get("llm")),
        ("Validation", f"{s.get('validation', '-')} {s.get('validation_summary', '')}"),
        ("Degradation", f"L{s.get('degradation_level', '-')}"),
        ("Final action", f"{s.get('final_action')} {s.get('final_comparison') or ''}"),
        ("Final file", s.get("final_file", "-- NONE --")),
        ("SHA256", s.get("sha256", "-")),
        ("Deadline", f"{d.get('phase')} — cutoff {d.get('cutoff')} ({d.get('minutes_left')} min left)"),
        ("Submission state", f"{s.get('submission_state')} (a generated file is not a submission)"),
        ("Runtime", f"{s.get('total_sec')} s; SLA breaches {[x['metric'] for x in s.get('sla', []) if x['breach']]}"),
    ]
    lines += ["| item | value |", "|---|---|"] + [f"| {k} | {str(v).replace('|', '/')} |" for k, v in rows]
    if s.get("notes"):
        lines += ["", "## Notes", ""] + [f"- {n}" for n in s["notes"]]
    out = reports_dir(ops_cfg) / f"{ymd(s['trade_date'])}_OPERATOR_SUMMARY.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def write_eod_report(trade_date: str, settlement, *, ops_cfg: dict | None = None, next_date: str | None = None) -> Path:
    """After T's internal settlement: what was executed, NAV, warnings, dividends, readiness for T+1."""
    from agent.ops.package_submission import active_final
    from agent.ops.settlement import path_for
    ops_cfg = ops_cfg or load_ops_config()
    fin = active_final(trade_date, ops_cfg)
    rec_p = path_for(trade_date, "reconciliation", ops_cfg)
    off_p = path_for(trade_date, "official", ops_cfg)
    ex = settlement.executions or []
    filled = [e for e in ex if e.get("status") == "FILLED"]
    issues = []
    if fin is None:
        issues.append("no FINAL_CANDIDATE for this date (treated as not submitted)")
    if settlement.warnings:
        issues.append(f"warnings today: {[w['rule'] for w in settlement.warnings]}")
    if not off_p.exists():
        issues.append(f"official settlement for {trade_date} not entered yet (needed before the next run)")
    lines = [f"# End of day {trade_date}", "",
             "| item | value |", "|---|---|",
             f"| FINAL submitted file | {fin['file'] + ' ' + fin['sha256'][:23] if fin else '-- none --'} |",
             f"| Orders / executions | {len(settlement.orders)} orders, {len(filled)} filled, "
             f"{len(ex) - len(filled)} not filled |",
             f"| Internal NAV | {float(settlement.nav):,.0f} (+ accrued {float(settlement.accrued_dividends):,.0f}) |",
             f"| Cash | {float(settlement.cash):,.0f} ({float(settlement.cash / settlement.nav):.2%}) |",
             f"| Holdings | {len(settlement.holdings)} |",
             f"| Fees / tax today | {float(settlement.fees):,.0f} / {float(settlement.tax):,.0f} |",
             f"| Warnings today / total | {len(settlement.warnings)} / {settlement.warning_count} |",
             f"| Dividends accrued | {float(settlement.accrued_dividends):,.0f} |",
             f"| Official settlement entered | {'yes' if off_p.exists() else 'NO'} |",
             f"| Internal vs official | {json.loads(rec_p.read_text(encoding='utf-8'))['status'] if rec_p.exists() else 'not reconciled yet'} |",
             f"| Tomorrow ({next_date or 'next trading day'}) readiness | "
             f"{'OK' if not issues else 'ACTION NEEDED'} |", ""]
    if issues:
        lines += ["## Unresolved", ""] + [f"- {i}" for i in issues]
    out = reports_dir(ops_cfg) / f"{ymd(trade_date)}_EOD.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(out.with_suffix(".json"), {"trade_date": trade_date, "issues": issues, "nav": str(settlement.nav)})
    return out
