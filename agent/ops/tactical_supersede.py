"""Issue #49 — Owner-authorised supersession of a SUBMISSION_CONFIRMED FINAL by the TACTICAL_OVERRIDE_V2 FINAL (same trade date).

Why a dedicated entry point: after SUBMISSION_CONFIRMED the daily flow deliberately refuses any new decision for that
trade date (competition_day: SUBMISSION_ALREADY_ACCEPTED; morning_final: ALREADY_SUBMITTED). The Owner decided on GitHub
(Issue #49, authorization comment 2026-11-08T18:00:27Z) that a later, stricter FINAL replaces the confirmed one; the portal
rule is "the last successful submission before 08:55 counts". Nothing here weakens a gate:

  * only for the trade date covered by an ENABLED TACTICAL_OVERRIDE_V2 config (phase ENTRY), before the 08:30 decision cutoff;
  * the portal must CURRENTLY show the prior FINAL as SUBMISSION_CONFIRMED (read-only check) - otherwise nothing is touched;
  * everything of the prior submission (FINAL, state, receipts, history) is archived first under submissions/<T>/superseded/;
  * the new candidate comes from the unchanged competition_day flow (data / DataPack / validation / compliance gates) and is
    promoted only if the V2 record says APPLIED with technology weight strictly below the target (candidate_gate);
  * if anything fails, the submission state goes back to SUBMISSION_CONFIRMED for the prior FINAL (it is still what the
    portal holds) and the reason is recorded;
  * the portal submission itself is the existing guarded auto_upload (same FINAL-sha rules, attempt caps, 08:55 hard stop,
    SUBMISSION_CONFIRMED only from real portal evidence: history row + 回看 == the new FINAL).

    python -m agent.ops.tactical_supersede --date 2026-11-09 --authorization "Issue #49 ..." [--check-only]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.ops.common import TPE, load_ops_config, ops_path, write_json, ymd  # noqa: E402

LOG = ROOT / "logs" / "tactical" / "supersede.jsonl"
OPERATOR = "tactical_supersede_v2"


def candidate_gate(summary: dict | None, tcfg: dict, run_id: str | None) -> tuple[bool, list[str]]:
    """Pure: may this competition_day candidate replace the confirmed FINAL? Every condition must hold (fail closed)."""
    from agent.tactical import override as TO
    s = summary or {}
    t = s.get("tactical_override") or {}
    why = []
    if run_id is None or s.get("run_id") != run_id:
        why.append("summary does not belong to the candidate run")
    if s.get("status") != "READY_TO_SUBMIT":
        why.append(f"run status {s.get('status')}")
    if s.get("validation") != "PASS":
        why.append(f"validation {s.get('validation')}")
    if t.get("version") != TO.VERSION_V2 or t.get("phase") != "ENTRY":
        why.append(f"tactical version/phase {t.get('version')}/{t.get('phase')} (V2 ENTRY required)")
    if t.get("status") != "APPLIED":
        why.append(f"tactical status {t.get('status')} {t.get('reason') or ''}".strip())
    if t.get("fingerprint") != tcfg.get("_fingerprint"):
        why.append("tactical fingerprint differs from the deployed V2 config")
    tw, tmax = t.get("tech_weight_after"), float(tcfg["target_tech_weight_max"])
    if tw is None or not float(tw) < tmax:
        why.append(f"technology weight {tw} is not strictly below {tmax}")
    n = t.get("holdings_after")
    if n is None or not (20 <= int(n) <= 30):
        why.append(f"holdings {n} not in 20-30")
    if (t.get("active_share_min") is None) or float(t["active_share_min"]) < 0.15:
        why.append(f"Active Share {t.get('active_share_min')} below 0.15")
    return (not why), why


def _log(row: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    row = dict(row, at=datetime.now(TPE).replace(microsecond=0).isoformat())
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def archive_prior(trade_date: str, ops: dict, prior_sha: str) -> Path:
    day = ops_path(ops, "submissions_dir") / ymd(trade_date)
    dst = day / "superseded" / prior_sha.split(":")[-1][:12]
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("submission_state.json", "receipts.jsonl", "final_history.jsonl", "FINAL_FREEZE.json", "FINAL_CANDIDATE.txt"):
        if (day / name).exists():
            shutil.copy2(day / name, dst / name)
    if (day / "FINAL").is_dir():
        shutil.copytree(day / "FINAL", dst / "FINAL", dirs_exist_ok=True)
    return dst


def preconditions(trade_date: str, ops: dict, now: datetime) -> dict:
    """Read-only. Returns {ok, reasons, ...context}."""
    from agent.ops import morning_final as MF
    from agent.ops.package_submission import active_final
    from agent.ops.scheduled_run import holidays, run_mode
    from agent.ops.team import resolve
    from agent.submission.base import CONFIRMED, get_state
    from agent.tactical import override as TO
    out = {"ok": False, "reasons": [], "trade_date": trade_date}
    tcfg = TO.resolve_config(None, trade_date)
    out["tactical_version"] = (tcfg or {}).get("version")
    if tcfg is None or tcfg["version"] != TO.VERSION_V2 or TO.phase_for(tcfg, trade_date) != "ENTRY":
        out["reasons"].append("no enabled TACTICAL_OVERRIDE_V2 ENTRY config for this trade date")
        return out
    out["tactical_fingerprint"] = tcfg["_fingerprint"]
    if run_mode(ops) != "COMPETITION":
        out["reasons"].append("not COMPETITION mode")
    if resolve("COMPETITION", ops)["status"] != "OK":
        out["reasons"].append("Team ID not configured")
    p = MF.plan(now, holidays(ops), ops)
    if p["action"] != "RUN" or p.get("trade_date") != trade_date:
        out["reasons"].append(f"decision window: {p['action']} {p.get('reason')} (a new decision needs < 08:30 on T)")
    prior = active_final(trade_date, ops)
    out["prior_final_sha256"] = (prior or {}).get("sha256")
    if not prior:
        out["reasons"].append("no active FINAL to supersede")
    elif (prior.get("tactical") or {}).get("version") == TO.VERSION_V2:
        out["reasons"].append("the active FINAL is already the V2 FINAL")
    st = get_state(trade_date, ops).get("state")
    out["state"] = st
    if st != CONFIRMED:
        out["reasons"].append(f"submission state {st} (this tool supersedes a SUBMISSION_CONFIRMED FINAL only)")
    out["ok"] = not out["reasons"]
    out["tcfg"] = tcfg
    return out


def run(trade_date: str, *, authorization: str, expect_prior_sha: str | None = None, check_only: bool = False,
        now: datetime | None = None, portal_verify=None, runner=None) -> dict:
    """`portal_verify(trade_date, ops) -> dict` and `runner(**kw) -> morning_final rec` are injectable for tests."""
    from agent.ops import morning_final as MF
    from agent.ops.final import replace_final
    from agent.submission.base import CONFIRMED, UNKNOWN, get_state, set_state
    ops = load_ops_config()
    now = now or datetime.now(TPE)
    rec = {"task": "tactical_supersede", "trade_date": trade_date, "authorization": authorization, "status": None,
           "operator": OPERATOR, "started_at": now.replace(microsecond=0).isoformat()}
    pre = preconditions(trade_date, ops, now)
    tcfg = pre.pop("tcfg", None)
    rec.update(prior_final_sha256=pre.get("prior_final_sha256"), tactical_version=pre.get("tactical_version"),
               tactical_fingerprint=pre.get("tactical_fingerprint"), state_before=pre.get("state"))
    if not pre["ok"]:
        rec.update(status="BLOCKED", blocked_reason="; ".join(pre["reasons"]))
        _log(rec)
        return rec
    prior_sha = pre["prior_final_sha256"]
    if expect_prior_sha and expect_prior_sha.split(":")[-1] != prior_sha.split(":")[-1]:
        rec.update(status="BLOCKED", blocked_reason=f"active FINAL {prior_sha} != expected {expect_prior_sha}")
        _log(rec)
        return rec
    verify = portal_verify or (lambda t, o: __import__("agent.submission.confirmation", fromlist=["verify"]).verify(t, ops_cfg=o))
    pv = verify(trade_date, ops)                      # read-only: the portal must hold the prior FINAL as SUBMISSION_CONFIRMED
    rec["portal_prior_check"] = {k: pv.get(k) for k in ("status", "final_sha256", "history_entry", "reasons", "matching_rows")}
    if pv.get("status") != "SUBMISSION_CONFIRMED":
        rec.update(status="BLOCKED", blocked_reason=f"portal does not show the prior FINAL as SUBMISSION_CONFIRMED "
                                                    f"({pv.get('status')}: {pv.get('reasons')}); nothing changed")
        _log(rec)
        return rec
    if check_only:
        rec.update(status="CHECK_OK", blocked_reason=None)
        _log(rec)
        return rec

    arch = archive_prior(trade_date, ops, prior_sha)
    rec["prior_archive"] = str(arch.relative_to(ROOT)) if arch.is_relative_to(ROOT) else str(arch)
    set_state(trade_date, UNKNOWN, cfg=ops, reason=f"Owner-authorised supersession by {tcfg['version']} ({authorization}); "
              f"prior {prior_sha} stays archived and is restored if the supersession does not complete")

    def tactical_replace(t, team, run_id, *, reason, operator):
        try:
            summary = json.loads((ops_path(ops, "ops_logs_dir") / ymd(t) / "competition_day_summary.json")
                                 .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            summary = None
        ok, why = candidate_gate(summary, tcfg, run_id)
        rec["candidate_gate"] = {"ok": ok, "reasons": why}
        if not ok:
            return {"ok": False, "reasons": ["candidate_gate: " + "; ".join(why)]}
        return replace_final(t, team, run_id, reason=f"{authorization}: {reason}", operator=OPERATOR)

    try:
        mrec = (runner or MF.run)(portal_check=lambda t, o: (True, f"Owner-authorised supersession ({authorization}): "
                                                               f"portal holds prior FINAL {prior_sha[:20]} as SUBMISSION_CONFIRMED"),
                                  replace=tactical_replace)
    except Exception as e:  # noqa: BLE001
        mrec = {"status": "FAILED", "error_message": f"{type(e).__name__}: {e}"[:300], "superseded": False}
    rec["morning_run"] = {k: mrec.get(k) for k in ("status", "blocked_reason", "error_message", "final_action", "superseded",
                                                  "new_final_sha256", "submission_state", "auto_upload_status",
                                                  "candidate_run_id", "supersede_reason")}
    from agent.ops.package_submission import active_final
    fin = active_final(trade_date, ops) or {}
    rec["active_final_sha256"] = fin.get("sha256")
    if not mrec.get("superseded"):
        # nothing replaced: the prior FINAL is still the active FINAL and still the portal's confirmed submission
        if get_state(trade_date, ops).get("state") == UNKNOWN and fin.get("sha256") == prior_sha:
            set_state(trade_date, CONFIRMED, cfg=ops, reason="supersession not performed; the prior FINAL stays the "
                      "confirmed portal submission", dplan_sha256=prior_sha)
        rec.update(status="NOT_SUPERSEDED", blocked_reason=mrec.get("blocked_reason") or mrec.get("error_message")
                   or mrec.get("supersede_reason") or "candidate not promoted")
    else:
        st = get_state(trade_date, ops).get("state")
        rec["state_after"] = st
        rec["status"] = "SUPERSEDED_CONFIRMED" if st == CONFIRMED else "SUPERSEDED_NOT_CONFIRMED"
    rec["finished_at"] = datetime.now(TPE).replace(microsecond=0).isoformat()
    _log(rec)
    write_json(ROOT / "logs" / "tactical" / f"supersede_{ymd(trade_date)}_latest.json", rec)
    return rec


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--authorization", required=True, help="where the Owner authorised this (e.g. Issue #49 comment)")
    ap.add_argument("--expect-prior-sha", default=None)
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args(argv)
    r = run(a.date, authorization=a.authorization, expect_prior_sha=a.expect_prior_sha, check_only=a.check_only)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    return 0 if r["status"] in ("SUPERSEDED_CONFIRMED", "CHECK_OK") else 2


if __name__ == "__main__":
    raise SystemExit(main())
