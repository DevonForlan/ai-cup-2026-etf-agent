"""FINAL_CANDIDATE operations (Round 06).

  python agent\\ops\\final.py show --date 2026-10-27
  python agent\\ops\\final.py replace-final --date 2026-10-27 --team-id TEAM_042 --run-id <run_id> ^
         --reason "why" --operator "name" [--mode competition]
  python agent\\ops\\final.py prepare --date 2026-10-27 --team-id TEAM_042     (verify FINAL -> READY_TO_SUBMIT)

replace-final is the ONLY way to change a frozen FINAL; it keeps the old record in final_history.jsonl,
compares old vs new candidate and refuses after the submission cutoff.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.ops.common import Clock, load_ops_config, ops_path, ymd  # noqa: E402
from agent.ops.package_submission import active_final, history, mark_final  # noqa: E402


def replace_final(trade_date: str, team_id: str, run_id: str, *, reason: str, operator: str, mode: str = "competition",
                  ops_cfg: dict | None = None, clock: Clock | None = None) -> dict:
    from agent.ops import deadline as DL
    from agent.ops.compare_candidates import compare
    ops_cfg = ops_cfg or load_ops_config()
    d = DL.status(trade_date, clock or Clock(), ops_cfg)
    if d.phase == "PAST_CUTOFF" and mode == "competition":
        return {"ok": False, "reasons": [f"past cutoff {d.cutoff.isoformat()}: FINAL cannot be replaced"]}
    day = ops_path(ops_cfg, "submissions_dir") / ymd(trade_date)
    new_pkg = day / "candidates" / run_id
    if not new_pkg.exists():
        return {"ok": False, "reasons": [f"candidate {run_id} not found"]}
    cur = active_final(trade_date, ops_cfg)
    cmp = compare(day / "candidates" / cur["run_id"], new_pkg) if cur else None
    res = mark_final(new_pkg, team_id=team_id, trade_date=trade_date, mode=mode, ops_cfg=ops_cfg, operator=operator,
                     replace=True, reason=reason, cutoff=d.cutoff.isoformat())
    res["comparison"] = cmp and {"class": cmp["class"], "reason": cmp["reason"]}
    if res.get("ok") and mode == "competition":
        from agent.submission.base import NOT_READY, READY, get_state, set_state
        if get_state(trade_date, ops_cfg)["state"] not in (NOT_READY,):
            set_state(trade_date, READY, reason=f"FINAL replaced by {operator}: {reason}", cfg=ops_cfg,
                      dplan_sha256=res["sha256"])
    return res


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["show", "replace-final", "prepare"])
    ap.add_argument("--date", required=True)
    ap.add_argument("--team-id")
    ap.add_argument("--run-id")
    ap.add_argument("--reason", default="")
    ap.add_argument("--operator", default="")
    ap.add_argument("--mode", default="competition", choices=["competition", "dry-run", "historical"])
    a = ap.parse_args(argv)
    if a.action == "show":
        print(json.dumps({"active": active_final(a.date), "history": history(a.date)}, indent=1, ensure_ascii=False))
        return 0
    if a.action == "prepare":
        from agent.submission.manual import ManualSubmissionProvider
        r = ManualSubmissionProvider().prepare(a.date, a.team_id)
        print(json.dumps(r, indent=1, ensure_ascii=False))
        return 0 if r["ok"] else 2
    r = replace_final(a.date, a.team_id, a.run_id, reason=a.reason, operator=a.operator, mode=a.mode)
    print(json.dumps(r, indent=1, ensure_ascii=False, default=str))
    return 0 if r.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
