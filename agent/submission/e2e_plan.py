"""Next-valid-window REAL_E2E plan (Issue #4): computes the next official trade date and its submission window from
the official calendar and writes the plan + runbook. Read-only: never generates a decision, never uploads.

    .venv\\Scripts\\python.exe -m agent.submission.e2e_plan [--now 2026-10-23T19:00:00+08:00]
        -> reports/REAL_E2E_PLAN.json and docs/REAL_E2E_RUNBOOK.md

E2E_PREPARATION_STATUS: WAITING_FOR_DECISION_WINDOW (window not open yet: the D-Plan for T cannot be generated
legally, so it is NOT pre-built) | FINAL_READY (a validated FINAL for T exists) | DECISION_WINDOW_OPEN (window open,
no FINAL yet) | DECISION_WINDOW_CLOSED (08:30 passed: only an existing FINAL may be uploaded) | WINDOW_CLOSED.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.ops.common import TPE, load_ops_config, write_json  # noqa: E402

PY = r".venv\Scripts\python.exe"


def build_plan(now: datetime | None = None, ops_cfg: dict | None = None) -> dict:
    from agent.config import load_official_rules
    from agent.ops import submission_window as SW
    from agent.submission.official_test import target_trade_date
    from agent.submission.status import compute
    ops = ops_cfg or load_ops_config()
    now = now or datetime.now(TPE)
    t = target_trade_date(now)
    tm = SW.times_for(t, ops)
    rules = load_official_rules().raw
    first = str(rules["official_rules"].get("first_trade_date") or "")
    team = (ops.get("team") or {}).get("competition_team_id")
    fname = rules["dplan"]["filename_pattern"].format(team_id=team, trade_date=t)
    phase = SW.phase(t, now, ops)
    st = compute(t, now=now, ops_cfg=ops)
    if st.get("file") and st["state"] in ("READY_FOR_UPLOAD", "FILE_UPLOADED", "SERVER_VALIDATED", "SUBMITTED",
                                          "ACCEPTED", "SUBMISSION_CONFIRMED"):
        prep = "FINAL_READY"
    else:
        prep = {"WINDOW_NOT_OPEN": "WAITING_FOR_DECISION_WINDOW", "DECISION_OPEN": "DECISION_WINDOW_OPEN",
                "DECISION_WINDOW_CLOSED": "DECISION_WINDOW_CLOSED"}.get(phase, "WINDOW_CLOSED")
    initial = t == first
    mode = ops.get("run_mode")
    a = ops.get("auto_upload") or {}
    init = " --initial" if initial else ""
    return {
        "generated_at": now.replace(microsecond=0).isoformat(),
        "target_trade_date": t, "is_first_competition_trade_date": initial,
        "window_opens": tm["opens"].isoformat(), "decision_cutoff": tm["decision_cutoff"].isoformat(),
        "window_closes": tm["closes"].isoformat(),
        "deadline_warnings": ["08:00 SUBMISSION_WARNING_0800", "08:15 SUBMISSION_HIGH_WARNING_0815",
                              "08:45 SUBMISSION_CRITICAL_WARNING_0845"],
        "team_id": team, "expected_filename": fname, "max_upload_bytes": (ops.get("submission") or {}).get("max_upload_bytes"),
        "portal_url": (ops.get("submission") or {}).get("portal_url"),
        "E2E_PREPARATION_STATUS": prep, "submission_state_now": st["state"], "window_phase_now": phase,
        "run_mode_now": mode,
        "run_mode_required": "COMPETITION" if t >= first else "PRECOMPETITION",
        "run_mode_note": ("T is a competition trade date: the Owner switches config/ops.yaml run_mode to COMPETITION "
                          "before the window opens (Owner decision; Claude Code never switches it).")
        if (t >= first and mode != "COMPETITION") else None,
        "auto_upload_enabled": bool(a.get("enabled")),
        "upload_path": "MANUAL (auto_upload disabled pending REAL_E2E; the Owner uploads in the portal)"
        if not a.get("enabled") else "AUTOMATED (guarded) with manual fallback",
        "rehearsal_window": (ops.get("submission") or {}).get("rehearsal_window"),
        "strategy_document_deadline": (ops.get("submission") or {}).get("strategy_document_deadline"),
        "STRATEGY_DOCUMENT_STATUS": (ops.get("submission") or {}).get("strategy_document_status") or "UNKNOWN",
        "owner_prerequisites": [
            ("ETF 投資策略說明文件: SUBMITTED "
             f"({(ops.get('submission') or {}).get('strategy_document_submitted_at')}; Issue #12 / PR #13) -- no action."
             if (ops.get("submission") or {}).get("strategy_document_status") == "SUBMITTED" else
             f"ETF 投資策略說明文件 (PDF) must be uploaded before "
             f"{(ops.get('submission') or {}).get('strategy_document_deadline')}."),
            "Optional (Owner decision): the 開賽前試繳 rehearsal "
            f"{((ops.get('submission') or {}).get('rehearsal_window') or {}).get('opens')} -> "
            f"{((ops.get('submission') or {}).get('rehearsal_window') or {}).get('closes')} validates an uploaded D-Plan "
            "for the first trade date without collecting or counting it; a manual trial upload there shows the real "
            "檢核結果 wording (PENDING_WINDOW_ONLY validation markers) before the real window.",
            "Log in to the portal ONCE in the automation profile (data/browser_profiles/fundaiagent) the normal way; "
            "the agent never types credentials and never reads cookies / tokens.",
            f"{PY} -m agent.submission.portal_driver readonly-test  ->  PORTAL_READONLY_REAL_TEST = PASS",
            "Machine on, network up, the 19:30 Task Scheduler task enabled (StartWhenAvailable).",
        ],
        "commands": {
            "plan": f"{PY} -m agent.submission.e2e_plan",
            "preflight": f"{PY} agent\\ops\\preflight.py --date {t} --mode competition --competition-profile prod{init}",
            "prepare_scheduled": "Task Scheduler 19:30 task (agent/ops/scheduled_run.py) -> FINAL + validation + "
                                 "submission stage",
            "prepare_manual": f"{PY} agent\\competition_day.py --date {t} --team-id {team} --mode competition "
                              f"--competition-profile prod{init}",
            "status": f"{PY} -m agent.submission.status --date {t}",
            "portal_discovery": f"{PY} -m agent.submission.portal_driver discover --wait-login 600",
            "portal_readonly_test": f"{PY} -m agent.submission.portal_driver readonly-test",
            "auto_upload_gate_check": f"{PY} -m agent.submission.auto_upload --date {t} --check",
            "real_upload_manual": f"Portal 文件繳交: upload ONLY {fname} (sha256 from status) -> 檢核結果 PASS -> "
                                  "送出繳交 -> 歷史繳交紀錄 (screenshot + verbatim row)",
            "real_upload_automated": f"{PY} -m agent.submission.auto_upload --date {t} --run   "
                                     "(only after ENABLE_AUTO_UPLOAD_RECOMMENDATION is approved by the Owner)",
            "verification_record": f"{PY} -m agent.submission.receipt --date {t} --team-id {team} --sha256 <sha256> "
                                   "--method manual_web --official-status accepted --stage accepted "
                                   "--history-entry \"<verbatim row>\" --evidence <screenshot.png> "
                                   "--confirmed-by \"<name>\"",
            "datapack": f"{PY} -m agent.submission.handoff --date {t}",
            "datapack_import": f"{PY} -m agent.ops.datapack --file <downloaded DataPack.json> --team-id {team} "
                               f"--trade-date <next trade date> --operator \"<name>\"",
        },
        "during_window_read_only_capture": [
            "After upload (before 送出繳交) and after submit: run portal_driver discover (read-only) so the "
            "PENDING_WINDOW_ONLY selectors / wording can be confirmed from the real page.",
            "Update ONLY config/portal_adapter.yaml (PENDING -> CONFIRMED_REAL_E2E) in a PR; never guess.",
        ],
        "fallback": [
            "Any automation failure -> data/submission_evidence/<T>/MANUAL_UPLOAD_REQUIRED.json (file, sha256, "
            "steps); upload manually.",
            "08:30: no new decision; only the existing FINAL. 08:55: no submit.",
            "Never upload a different SHA for the same trade date via automation; never use all 25 official attempts.",
            "Rollback = nothing to roll back (auto_upload stays disabled); the FINAL file is never edited.",
        ],
    }


def render_runbook(plan: dict) -> str:
    c = plan["commands"]
    lines = [
        "# REAL_E2E runbook — next valid submission window (Issue #4)",
        "",
        f"Generated by `agent/submission/e2e_plan.py` at {plan['generated_at']} (re-run it to refresh).",
        "",
        "| Item | Value |", "|---|---|",
        f"| Target trade date | **{plan['target_trade_date']}**"
        + (" (first competition trade date)" if plan["is_first_competition_trade_date"] else "") + " |",
        f"| Window opens | {plan['window_opens']} |",
        f"| Decision cutoff | {plan['decision_cutoff']} |",
        f"| Window closes | {plan['window_closes']} |",
        f"| Team ID | {plan['team_id']} |",
        f"| Expected file | `{plan['expected_filename']}` (≤ {plan['max_upload_bytes']} bytes) |",
        f"| Preparation status | `{plan['E2E_PREPARATION_STATUS']}` |",
        f"| Run mode now / required | {plan['run_mode_now']} / {plan['run_mode_required']} |",
        f"| Upload path | {plan['upload_path']} |",
        "",
    ]
    if plan.get("run_mode_note"):
        lines += [f"> {plan['run_mode_note']}", ""]
    lines += ["## 1. Owner prerequisites", ""] + [f"- {x}" for x in plan["owner_prerequisites"]] + [""]
    lines += [
        "## 2. Steps", "",
        f"1. Plan / dates: `{c['plan']}`",
        f"2. Preflight: `{c['preflight']}`",
        f"3. Prepare the FINAL (window open, before 08:30): {c['prepare_scheduled']}; manual equivalent "
        f"`{c['prepare_manual']}`",
        f"4. Status: `{c['status']}` → READY_FOR_UPLOAD with sha256",
        f"5. Portal check (read-only): `{c['portal_readonly_test']}`",
        f"6. Upload: {c['real_upload_manual']}",
        f"   - automated (later only): `{c['real_upload_automated']}`; gate only: `{c['auto_upload_gate_check']}`",
        f"7. Read-only capture for the adapter: `{c['portal_discovery']}`",
        f"8. Record the official result: `{c['verification_record']}`",
        f"9. After settlement, DataPack: `{c['datapack']}`; import: `{c['datapack_import']}`",
        "",
        "## 3. During the window (read-only capture)", "",
    ] + [f"- {x}" for x in plan["during_window_read_only_capture"]] + [
        "", "## 4. Fallback / rollback", "",
    ] + [f"- {x}" for x in plan["fallback"]] + [
        "",
        "## 5. Never",
        "",
        "- type credentials, read cookies / storage / tokens, call the portal's private /api, bypass SSO / MFA / CAPTCHA",
        "- generate a new decision after 08:30, submit at / after 08:55, edit the FINAL, change Quant v1",
        "- enable auto_upload without the Owner's approval",
        "",
    ]
    return "\n".join(lines)


def write(plan: dict, plan_path: Path | None = None, runbook_path: Path | None = None) -> tuple[Path, Path]:
    plan_path = plan_path or ROOT / "reports" / "REAL_E2E_PLAN.json"
    runbook_path = runbook_path or ROOT / "docs" / "REAL_E2E_RUNBOOK.md"
    write_json(plan_path, plan)
    runbook_path.write_text(render_runbook(plan), encoding="utf-8", newline="\n")
    return plan_path, runbook_path


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", default=None, help="ISO time (default: now, Asia/Taipei)")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now) if a.now else None
    plan = build_plan(now)
    pp, rp = write(plan)
    print(json.dumps({k: plan[k] for k in ("target_trade_date", "window_opens", "window_closes", "expected_filename",
                                           "E2E_PREPARATION_STATUS", "run_mode_now", "run_mode_required")},
                     ensure_ascii=False, indent=1))
    print(f"plan: {pp}\nrunbook: {rp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
