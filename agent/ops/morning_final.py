"""07:30 COMPETITION morning FINAL (Issue #20, Owner Decision 2026-10-27) — independent of the 19:30 prediction.

Called by automation/run_morning_final.ps1 (task AI_CUP_Competition_MorningFinal_0730, daily 07:30,
StartWhenAvailable=True, WakeToRun=False). For T = today (a trading day):

  lock (agent/ops/production_lock.py, shared with the 19:30 run)
  -> T already SUBMISSION_CONFIRMED / ACCEPTED: no new decision (competition_day refuses one too); verify only
  -> before 08:30: the SAME competition command as 19:30 (agent/competition_day.py --mode competition, refresh of
     the latest legal data, freshness / DataPack / validation / compliance gates unchanged) -> a candidate
       * no FINAL yet            -> competition_day marks it (MARKED)
       * KEPT_IDENTICAL          -> the evening FINAL stays (same decisions)
       * KEPT_DIFFERENT          -> supersede ONLY if supersede_decision() passes (same T, data health PASS,
                                    validation PASS, every compliance item PASS, before 08:30) via final.replace_final
                                    (prior / new sha, reason and evidence kept; exactly one active FINAL)
  -> 08:30 .. 08:55: no decision; the EXISTING FINAL may still be uploaded / submitted / verified
  -> downstream submission runner (scheduled_run.submission_stage -> agent/submission/auto_upload.py, fail closed)
  -> logs/morning/latest_status.json + history.jsonl (PREDICTION_STATUS and SUBMISSION_STATUS kept apart)

Quant v1 is not touched: the decision is computed by the unchanged competition_day pipeline.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.ops.common import TPE, load_ops_config, ops_path, write_json, ymd  # noqa: E402

LOG_DIR = ROOT / "logs" / "morning"
TASK_NAME = "AI_CUP_Competition_MorningFinal_0730"
OPERATOR = "morning_final_0730"                     # replace_final needs a named, non-"agent" operator
LOCK_WAIT_S = 10 * 60
REQUIRED_COMPLIANCE = ("Universe 150", "Holdings 20-30", "2330 <= 25%", "Other stocks <= 10%", "Cash < 25%",
                       "Active Share official >= 15%", "Strategy consistency", "D-Plan validation")
SUBMITTABLE = ("READY_FOR_UPLOAD", "FILE_UPLOADED", "SERVER_VALIDATED", "SUBMITTED")
DONE = ("ACCEPTED", "SUBMISSION_CONFIRMED")


# ----------------------------------------------------------------------------- pure logic (unit tested)
def plan(now: datetime, hol: set[str], ops_cfg: dict | None = None) -> dict:
    """RUN (decision allowed, < 08:30) | SUBMIT_EXISTING_ONLY (08:30 .. 08:55) | SKIP."""
    from agent.ops import submission_window as SW
    t = now.date()
    out = {"trade_date": t.isoformat(), "action": "RUN", "reason": None, "window_phase": None,
           "actual_start_time": now.replace(microsecond=0).isoformat()}
    if t.weekday() >= 5 or t.isoformat() in hol:
        out.update(action="SKIP", reason="NO_TRADING_DAY", trade_date=None)
        return out
    ph = SW.phase(t.isoformat(), now, ops_cfg)
    out["window_phase"] = ph
    if ph == "SUBMISSION_WINDOW_CLOSED":
        out.update(action="SKIP", reason="SUBMISSION_WINDOW_CLOSED")
    elif ph == "DECISION_WINDOW_CLOSED":
        out.update(action="SUBMIT_EXISTING_ONLY", reason="DECISION_WINDOW_CLOSED (08:30: no new investment decision)")
    elif ph != "DECISION_OPEN":
        out.update(action="SKIP", reason=ph)
    return out


def supersede_decision(summary: dict | None, prior: dict | None, *, trade_date: str, now: datetime,
                       ops_cfg: dict | None = None) -> tuple[bool, str]:
    """May the morning candidate replace the evening FINAL? Every condition must hold (fail closed)."""
    from agent.ops import submission_window as SW
    s = summary or {}
    if prior is None:
        return False, "no prior FINAL (competition_day marks the first FINAL itself)"
    why = []
    if s.get("trade_date") != trade_date or prior.get("trade_date") != trade_date:
        why.append("trade date mismatch")
    if s.get("mode") != "competition" or prior.get("mode") != "competition":
        why.append("not a competition run / FINAL")
    if s.get("status") != "READY_TO_SUBMIT":
        why.append(f"run status {s.get('status')}")
    if s.get("final_action") != "KEPT_DIFFERENT":
        why.append(f"final_action {s.get('final_action')} (only a different decision supersedes)")
    if s.get("data_health") != "PASS":
        why.append(f"data health {s.get('data_health')} (freshness not PASS)")
    if s.get("validation") != "PASS":
        why.append(f"validation {s.get('validation')}")
    cs = s.get("compliance_summary") or {}
    bad = [k for k in REQUIRED_COMPLIANCE if not str(cs.get(k, "MISSING")).startswith("PASS")]
    if bad:
        why.append(f"compliance not PASS: {bad}")
    if not s.get("run_id"):
        why.append("no candidate run_id")
    if now >= SW.times_for(trade_date, ops_cfg)["decision_cutoff"]:
        why.append("08:30 decision cutoff reached")
    return (not why), ("; ".join(why) if why else "morning refresh produced a different, fully validated decision")


# ----------------------------------------------------------------------------- io
def _finish(rec: dict) -> dict:
    from agent.ops.scheduled_run import split_status
    rec["finished_at"] = datetime.now(TPE).replace(microsecond=0).isoformat()
    split_status(rec)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    write_json(LOG_DIR / "latest_status.json", rec)
    with open(LOG_DIR / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def snapshot_summary(trade_date: str, ops_cfg: dict, sha256: str | None, summary: dict | None = None) -> Path | None:
    """Keep the competition_day summary of the FINAL with `sha256` (the next run rewrites the day's summary)."""
    day = ops_path(ops_cfg, "ops_logs_dir") / ymd(trade_date)
    if summary is None:
        try:
            summary = json.loads((day / "competition_day_summary.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    if not sha256 or summary.get("sha256") != sha256:
        return None
    p = day / "summaries" / f"{sha256.split(':')[-1]}.json"
    if not p.exists():
        write_json(p, summary)
    return p


def _run_competition_day(trade_date: str, team: str, pre: dict, started: str) -> tuple[dict | None, str | None]:
    cmd = [sys.executable, str(ROOT / "agent" / "competition_day.py"), "--date", trade_date, "--team-id", team,
           "--mode", pre["cd_mode"], "--competition-profile", "prod"] + pre["extra_args"]
    err = None
    try:
        cp = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=50 * 60)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        (LOG_DIR / f"competition_day_{ymd(trade_date)}_{started[11:19].replace(':', '')}.txt").write_text(
            cp.stdout[-20000:] + cp.stderr[-5000:], encoding="utf-8")
    except subprocess.TimeoutExpired:
        err = "competition_day timeout (50 min)"
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    ops = load_ops_config()
    try:
        s = json.loads((ops_path(ops, "ops_logs_dir") / ymd(trade_date) / "competition_day_summary.json")
                       .read_text(encoding="utf-8"))
        return (s if s.get("started_at", "") >= started[:16] else None), err
    except (OSError, ValueError):
        return None, err or "no competition_day summary"


def run(now: datetime | None = None, *, cd_runner=None, submit=None, replace=None, prepare=None) -> dict:
    """`cd_runner` / `submit` / `replace` / `prepare` are injectable for tests (defaults: the production calls)."""
    from agent.data.locks import LockTimeout
    from agent.ops.production_lock import production_lock
    from agent.ops.scheduled_run import holidays, run_mode
    now = now or datetime.now(TPE)
    ops = load_ops_config()
    p = plan(now, holidays(ops), ops)
    rec = {"task": TASK_NAME, "status": None, "run_mode": run_mode(ops), **p, "superseded": False,
           "prior_final_sha256": None, "new_final_sha256": None, "supersede_reason": None,
           "auto_upload_status": None, "blocked_reason": None, "error_message": None}
    if p["action"] == "SKIP":
        rec.update(status="SKIPPED", blocked_reason=p["reason"])
        return _finish(rec)
    if rec["run_mode"] != "COMPETITION":
        rec.update(status="SKIPPED", blocked_reason="NOT_COMPETITION_MODE")
        return _finish(rec)
    lk = production_lock(LOG_DIR.parent / "locks", wait_s=LOCK_WAIT_S)
    try:
        lk.acquire()
    except LockTimeout as e:
        rec.update(status="BLOCKED", blocked_reason="LOCK_UNAVAILABLE", error_message=str(e)[:300])
        return _finish(rec)
    try:
        return _locked(rec, now, ops, cd_runner=cd_runner, submit=submit, replace=replace, prepare=prepare)
    finally:
        lk.release()


def _locked(rec: dict, now: datetime, ops: dict, *, cd_runner, submit, replace, prepare) -> dict:
    from agent.ops.final import replace_final
    from agent.ops.package_submission import active_final
    from agent.ops.scheduled_run import RunLog, competition_preparation, submission_stage
    from agent.ops.team import resolve
    from agent.submission.status import compute
    t = rec["trade_date"]
    tm = resolve("COMPETITION", ops)
    if tm["status"] != "OK":
        rec.update(status="BLOCKED", blocked_reason="TEAM_ID_NOT_CONFIGURED")
        return _finish(rec)
    team = tm["team_id"]
    prior = active_final(t, ops)
    rec["prior_final_sha256"] = (prior or {}).get("sha256")
    sub = compute(t, ops_cfg=ops)
    rec["submission_state"] = sub["state"]
    if sub["state"] in DONE:
        rec.update(status="SKIPPED", blocked_reason="ALREADY_SUBMITTED (no new decision after a confirmed submission)")
    elif rec["action"] == "SUBMIT_EXISTING_ONLY":
        rec.update(status="SKIPPED", blocked_reason="DECISION_WINDOW_CLOSED")
    else:
        snapshot_summary(t, ops, rec["prior_final_sha256"])
        log = RunLog(now)
        pre = (prepare or competition_preparation)("COMPETITION", t, team, log)
        rec.update(datapack_status=pre.get("datapack_status"))
        if pre.get("blocked_reason"):
            rec.update(status="BLOCKED", blocked_reason=pre["blocked_reason"], error_message=pre.get("detail"))
        else:
            summary, err = (cd_runner or _run_competition_day)(t, team, pre, rec["actual_start_time"])
            s = summary or {}
            rec.update(cd_status=s.get("status"), final_action=s.get("final_action"), data_refresh=s.get("data_health"),
                       dplan_validation=s.get("validation"), candidate_run_id=s.get("run_id"))
            if err or not summary:
                rec.update(status="FAILED", error_message=err or "no competition_day summary for this run")
            elif s.get("status") != "READY_TO_SUBMIT":
                rec.update(status="BLOCKED", blocked_reason=f"competition_day {s.get('status')}: "
                                                            f"{str(s.get('reason'))[:200]}")
            else:
                rec["status"] = "PASS"
                if s.get("final_action") == "KEPT_DIFFERENT":
                    ok, why = supersede_decision(s, prior, trade_date=t, now=datetime.now(TPE), ops_cfg=ops)
                    rec["supersede_reason"] = why
                    if ok:
                        res = (replace or replace_final)(t, team, s["run_id"], reason=f"Issue #20 07:30: {why}",
                                                         operator=OPERATOR)
                        if res.get("ok"):
                            snap = dict(s, sha256=res["sha256"], final_run_id=s["run_id"])
                            snapshot_summary(t, ops, res["sha256"], snap)
                            rec.update(superseded=True, new_final_sha256=res["sha256"])
                            _supersede_log(t, ops, prior, res, why, s)
                        else:
                            rec["supersede_reason"] = f"replace_final refused: {res.get('reasons')}"
                elif s.get("final_action") == "MARKED":
                    rec["new_final_sha256"] = s.get("sha256")
    fin = active_final(t, ops)
    rec["active_final_sha256"] = (fin or {}).get("sha256")
    rec["active_final_path"] = (fin or {}).get("path")
    sub = compute(t, ops_cfg=ops)
    if fin and sub["state"] in SUBMITTABLE:
        try:
            (submit or submission_stage)(t, "COMPETITION", rec)
        except Exception as e:  # noqa: BLE001 - a submission problem never hides the decision result
            rec.update(auto_upload_status="FAIL_CLOSED", manual_action_required=True,
                       last_error=f"{type(e).__name__}: {str(e)[:200]}")
    rec["submission_state"] = compute(t, ops_cfg=ops)["state"]
    rec["manual_action_required"] = rec["submission_state"] not in DONE
    return _finish(rec)


def _supersede_log(trade_date: str, ops: dict, prior: dict | None, res: dict, why: str, summary: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(TPE).replace(microsecond=0).isoformat(), "trade_date": trade_date,
           "prior_final_sha256": (prior or {}).get("sha256"), "prior_run_id": (prior or {}).get("run_id"),
           "new_final_sha256": res.get("sha256"), "new_run_id": summary.get("run_id"),
           "generated_at": summary.get("finished_at") or summary.get("started_at"), "reason": why,
           "comparison": res.get("comparison"), "evidence": f"submissions/{ymd(trade_date)}/final_history.jsonl"}
    with open(LOG_DIR / "supersede.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rec = run()
    print(f"MORNING_FINAL {rec['status']} {rec.get('blocked_reason') or ''} prediction={rec.get('prediction_status')} "
          f"submission={rec.get('submission_status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
