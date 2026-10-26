"""Day-1 18:00 verification — READ ONLY (Issue #16; Owner decisions 2026-10-26: Decision 1 = A, Decision 2 = A).

Runs once at 2026-10-26 18:00 +08:00 (Task Scheduler AI_CUP_Day1_Verify_1800) before the formal 19:30 Day-1 run.
It never edits config, never commits / pushes, never generates a decision or a D-Plan, never touches the portal.

    .venv\\Scripts\\python.exe -m agent.ops.day1_verify [--trade-date 2026-10-27] [--dry-run]

Result: logs/ops/day1/verify_<timestamp>.json, logs/ops/day1/latest.json, logs/ops/day1/verify.jsonl, with
RUN_MODE_SWITCH_STATUS = PASS | FAIL and MANUAL_ACTION_REQUIRED = YES on failure (exit code 0 / 2). No silent
failure: an exception becomes FAIL with the reason. --dry-run only labels the record (the checks are read-only anyway).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.ops.common import TPE, load_ops_config, ops_path, sha256_file  # noqa: E402

DAY1 = "2026-10-27"
EXPECTED_PREV = "2026-10-22"
TEAM = "TEAM_11442"
FROZEN_SHA = "f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0"
FROZEN_PATHS = ["config/strategy_quant_v1.yaml", "agent/features", "agent/portfolio", "agent/pipeline.py",
                "agent/run_sim.py", "agent/sim"]
TASK_1930 = "AI_CUP_Precompetition_DryRun_1930"
TASK_1930_POLICY = {"StartWhenAvailable": True, "WakeToRun": False}     # recorded 2026-10-24; must be unchanged
NEXT_FORMAL_RUN = "2026-10-26T19:30:00+08:00"


def _git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"check": name, "status": "PASS" if ok else "FAIL", "detail": detail}


def git_checks() -> list[dict]:
    out = []
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    out.append(_check("branch_is_master", branch == "master", f"branch={branch}"))
    dirty = _git("status", "--porcelain", "--untracked-files=no")
    out.append(_check("worktree_clean", not dirty, "clean" if not dirty else f"dirty: {dirty.splitlines()[:5]}"))
    head = _git("rev-parse", "HEAD")
    remote = _git("ls-remote", "origin", "refs/heads/master").split()[0]     # read-only (no fetch)
    out.append(_check("master_in_sync_with_origin", head == remote, f"HEAD {head[:12]} origin/master {remote[:12]}"))
    diff = _git("diff", "--name-only", remote, "--", *FROZEN_PATHS) if remote else "unknown"
    out.append(_check("no_frozen_path_diff", diff == "", "none" if not diff else diff[:300]))
    return out


def config_checks(ops: dict) -> list[dict]:
    from agent.ops.datapack import calendar_holidays, previous_trading_day
    from agent.ops.refresh_daily import expected_prev_trading_day
    from agent.ops import scheduled_run as S
    from agent.ops.team import resolve
    out = []
    mode = S.run_mode(ops)
    out.append(_check("run_mode_competition", mode == "COMPETITION", f"run_mode={mode}"))
    t = resolve("COMPETITION", ops)
    out.append(_check("team_id", t["status"] == "OK" and t["team_id"] == TEAM, f"{t.get('team_id')} ({t['status']})"))
    h = sha256_file(ROOT / "config" / "strategy_quant_v1.yaml").replace("sha256:", "")
    out.append(_check("quant_fingerprint", h == FROZEN_SHA, h))
    au = (ops.get("auto_upload") or {}).get("enabled", False)
    out.append(_check("auto_upload_disabled", au is False, f"auto_upload.enabled={au}"))
    hol_ops, hol_cal = S.holidays(ops), calendar_holidays()
    out.append(_check("calendar_1023_closed", "2026-10-23" in hol_ops and "2026-10-23" in hol_cal and hol_ops == hol_cal,
                      f"in ops={'2026-10-23' in hol_ops} in trading_calendar={'2026-10-23' in hol_cal} consistent={hol_ops == hol_cal}"))
    p1, p2 = previous_trading_day(DAY1, hol_cal), expected_prev_trading_day(DAY1, hol_ops)
    out.append(_check("previous_trading_day", p1 == EXPECTED_PREV and p2 == EXPECTED_PREV, f"datapack={p1} refresh={p2}"))
    pl = S.plan(datetime.fromisoformat(NEXT_FORMAL_RUN), hol_ops, S.window_open_time(), ops_cfg=ops,
                close_hm=S.window_close_time())
    out.append(_check("plan_1930_targets_day1", pl["trade_date"] == DAY1 and pl["action"] == "RUN",
                      f"plan at {NEXT_FORMAL_RUN}: action={pl['action']} trade_date={pl['trade_date']} kind={pl.get('run_kind')}"))
    return out


def task_checks() -> list[dict]:
    ps = (f"$t = Get-ScheduledTask -TaskName '{TASK_1930}' -ErrorAction SilentlyContinue; if ($t) {{ $i = $t | "
          "Get-ScheduledTaskInfo; [pscustomobject]@{State=[string]$t.State; StartWhenAvailable=$t.Settings.StartWhenAvailable;"
          " WakeToRun=$t.Settings.WakeToRun; Next=[string]$i.NextRunTime; Trigger=($t.Triggers | ForEach-Object {$_.StartBoundary})"
          " -join ','} | ConvertTo-Json -Compress }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60)
    if not r.stdout.strip():
        return [_check("task_1930_exists", False, f"{TASK_1930} not found ({r.stderr.strip()[:120]})")]
    t = json.loads(r.stdout)
    return [_check("task_1930_exists", True, f"{TASK_1930} next={t['Next']} trigger={t['Trigger']}"),
            _check("task_1930_enabled", t["State"] != "Disabled", f"State={t['State']}"),
            _check("task_1930_policy_unchanged", t["StartWhenAvailable"] is TASK_1930_POLICY["StartWhenAvailable"]
                   and t["WakeToRun"] is TASK_1930_POLICY["WakeToRun"],
                   f"StartWhenAvailable={t['StartWhenAvailable']} WakeToRun={t['WakeToRun']}"),
            _check("task_1930_trigger_1930", "T19:30:00" in t["Trigger"], t["Trigger"])]


def preflight_checks() -> tuple[list[dict], dict]:
    """competition_preflight (READY / WARNING / BLOCKED items) + the standalone preflight --initial. FAIL only on
    BLOCKED / BLOCK; WARNING items are reported, not hidden."""
    from agent.ops import competition_preflight as CP
    res = CP.run(DAY1)
    blocked = [i for i in res["items"] if i["level"] == "BLOCKED"]
    warns = [f"{i['item']}: {i['detail']}" for i in res["items"] if i["level"] == "WARNING"]
    out = [_check("competition_preflight_no_blocked", not blocked,
                  f"overall={res['overall']}; blocked={[i['item'] + ': ' + i['detail'] for i in blocked]}")]
    r = subprocess.run([sys.executable, str(ROOT / "agent" / "ops" / "preflight.py"), "--date", DAY1, "--mode", "competition",
                        "--competition-profile", "prod", "--initial"], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
    lines = (r.stdout or "").splitlines()
    verdict = next((ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("PREFLIGHT:")), "UNKNOWN")
    blocks = [ln.strip() for ln in lines if ln.startswith("[BLOCK")]
    out.append(_check("preflight_competition_initial", verdict in ("PASS", "WARN") and not blocks,
                      f"PREFLIGHT {verdict}; blocks={blocks[:6]}"))
    warns += [ln.strip() for ln in lines if ln.startswith("[WARN")]
    return out, {"competition_preflight_overall": res["overall"], "preflight_verdict": verdict, "warnings": warns}


def verify(dry_run: bool = False) -> dict:
    now = datetime.now(TPE)
    rec = {"tool": "day1_verify", "read_only": True, "dry_run": dry_run, "checked_at": now.replace(microsecond=0).isoformat(),
           "DAY1_TARGET_TRADE_DATE": DAY1, "PREVIOUS_TRADING_DAY_EXPECTED": EXPECTED_PREV, "checks": [], "warnings": []}
    try:
        ops = load_ops_config()
        rec["checks"] += git_checks()
        rec["checks"] += config_checks(ops)
        rec["checks"] += task_checks()
        pf, info = preflight_checks()
        rec["checks"] += pf
        rec.update(info)
    except Exception as e:  # noqa: BLE001 - never silent: any error is a FAIL with the reason
        rec["checks"].append(_check("verification_error", False, f"{type(e).__name__}: {e}"))
        rec["traceback"] = traceback.format_exc()[-2000:]
    failed = [c for c in rec["checks"] if c["status"] != "PASS"]
    ok = not failed
    by = {c["check"]: c for c in rec["checks"]}
    rec.update({
        "RUN_MODE_SWITCH_STATUS": "PASS" if ok else "FAIL",
        "MANUAL_ACTION_REQUIRED": "NO" if ok else "YES",
        "RUN_MODE": by.get("run_mode_competition", {}).get("detail", "").replace("run_mode=", "") or None,
        "PREVIOUS_TRADING_DAY": EXPECTED_PREV if by.get("previous_trading_day", {}).get("status") == "PASS" else
        by.get("previous_trading_day", {}).get("detail"),
        "TEAM_ID": TEAM if by.get("team_id", {}).get("status") == "PASS" else by.get("team_id", {}).get("detail"),
        "QUANT_FREEZE": by.get("quant_fingerprint", {}).get("status", "UNKNOWN"),
        "AUTO_UPLOAD_ENABLED": "false" if by.get("auto_upload_disabled", {}).get("status") == "PASS" else "CHECK",
        "COMPETITION_PREFLIGHT": "PASS" if all(by.get(k, {}).get("status") == "PASS" for k in
                                                ("competition_preflight_no_blocked", "preflight_competition_initial")) else "FAIL",
        "NEXT_FORMAL_RUN": NEXT_FORMAL_RUN,
        "failure_reasons": [f"{c['check']}: {c['detail']}" for c in failed]})
    d = ops_path(load_ops_config(), "ops_logs_dir") / "day1"
    d.mkdir(parents=True, exist_ok=True)
    body = json.dumps(rec, ensure_ascii=False, indent=1, default=str)
    (d / f"verify_{now:%Y%m%d_%H%M%S}{'_dryrun' if dry_run else ''}.json").write_text(body, encoding="utf-8")
    (d / "latest.json").write_text(body, encoding="utf-8")
    with open(d / "verify.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({k: rec[k] for k in ("checked_at", "dry_run", "RUN_MODE_SWITCH_STATUS", "MANUAL_ACTION_REQUIRED",
                                                 "failure_reasons")}, ensure_ascii=False) + "\n")
    return rec


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    r = verify(a.dry_run)
    for c in r["checks"]:
        print(f"[{c['status']}] {c['check']:<36} {c['detail']}")
    for k in ("RUN_MODE_SWITCH_STATUS", "MANUAL_ACTION_REQUIRED", "RUN_MODE", "DAY1_TARGET_TRADE_DATE", "PREVIOUS_TRADING_DAY",
              "TEAM_ID", "QUANT_FREEZE", "AUTO_UPLOAD_ENABLED", "COMPETITION_PREFLIGHT", "NEXT_FORMAL_RUN"):
        print(f"{k} = {r.get(k)}")
    if r["failure_reasons"]:
        print("FAILURE_REASONS:", *r["failure_reasons"], sep="\n  ")
    return 0 if r["RUN_MODE_SWITCH_STATUS"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
