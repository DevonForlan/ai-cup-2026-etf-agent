"""Restore drill (Round 06): simulate a machine restart.

  python agent\\ops\\restore_drill.py --state rehearsal\\<clock-sim id> --next-date 2026-10-05 --team-id TEAM_REHEARSAL

1. back up the operational state of a rehearsal (agent/ops/backup.py, no keys / raw data)
2. `git worktree add --detach` a clean checkout of HEAD in a temp dir (the working tree is NOT touched)
3. restore the backup into a fresh state dir (hash-verified, no overwrite)
4. from the fresh checkout, run the NEXT trading day in competition mode against the restored state
5. verify: READY_TO_SUBMIT, reconciliation MATCH, starting settlement == restored ledger; remove the worktree
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.ops.common import write_json  # noqa: E402

CHILD = r'''
import json, sys
wt, state, hist, d, team, clk = sys.argv[1:7]
sys.path.insert(0, wt)
from pathlib import Path
from agent.ops.rehearsal import rehearsal_ops_cfg
from agent.ops.common import Clock
from agent.data.loaders import HistoryStore
from agent.competition_day import run_competition_day
from agent.ops.refresh_daily import replay_fetchers
import agent.config as C
cfg = rehearsal_ops_cfg(Path(state))
cfg["preflight"]["etf_stale_days_block"] = 99999
s = run_competition_day(d, team, "competition", clock=Clock(clk), ops_cfg=cfg, store=HistoryStore(hist),
                        refresh_fetchers=replay_fetchers(), archive_readonly=False, operator="restore-drill")
print("@@RESULT@@" + json.dumps({"status": s["status"], "reason": s.get("reason"), "start": s.get("start"),
      "reconciliation": (s.get("settlement") or {}).get("reconciliation"), "sha256": s.get("sha256"),
      "agent_root": str(C.ROOT), "preflight_warns": (s.get("preflight") or {}).get("warns")}, default=str))
'''


def drill(state_root: Path, next_date: str, team_id: str) -> dict:
    from agent.ops.backup import backup, restore
    from agent.ops.common import sha256_json
    from agent.ops.rehearsal import rehearsal_ops_cfg
    from agent.sim.models import Settlement
    state_root = Path(state_root).resolve()
    tmp = Path(tempfile.mkdtemp(prefix="restore_"))
    res = {"state_root": str(state_root), "next_date": next_date, "tmp": str(tmp)}
    z = backup(tmp / "bk", ops_cfg=rehearsal_ops_cfg(state_root), base=state_root)
    res["backup"] = {"zip": z.name, "size_kb": round(z.stat().st_size / 1024, 1)}
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    wt = tmp / "wt"
    r = subprocess.run(["git", "worktree", "add", "--detach", str(wt), sha], cwd=ROOT, capture_output=True, text=True)
    res["worktree"] = {"sha": sha[:7], "ok": r.returncode == 0, "err": r.stderr[-300:]}
    try:
        state = tmp / "state"
        res["restore"] = restore(z, state)
        prev = (date.fromisoformat(next_date) - timedelta(days=1)).isoformat()
        out = subprocess.run([sys.executable, "-c", CHILD, str(wt), str(state), str(ROOT / "data" / "history"),
                              next_date, team_id, f"{prev}T20:00:00+08:00"], capture_output=True, text=True,
                             timeout=900, encoding="utf-8", errors="replace")
        line = [x for x in out.stdout.splitlines() if x.startswith("@@RESULT@@")]
        child = json.loads(line[-1][10:]) if line else {"status": "CHILD_FAILED", "reason": out.stderr[-800:]}
        res["run"] = child
        # restored ledger of the last rehearsal day == starting point used by the fresh checkout
        ledger = sorted((state / "data" / "settlement").glob("*_internal.json"))[-1]
        s = Settlement.load(ledger)
        expect = sha256_json({"holdings": s.holdings, "cash": str(s.cash), "nav": str(s.nav)})
        res["continuity"] = {"ledger": ledger.name, "match": (child.get("start") or {}).get("settlement_hash") == expect}
        res["ran_from_worktree"] = Path(child.get("agent_root", "")).resolve() == wt.resolve()
        res["passed"] = (child.get("status") == "READY_TO_SUBMIT" and child.get("reconciliation") == "MATCH"
                         and res["continuity"]["match"] and res["ran_from_worktree"])
    finally:
        rm = subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=ROOT, capture_output=True, text=True)
        res["worktree_removed"] = rm.returncode == 0
        subprocess.run(["git", "worktree", "prune"], cwd=ROOT, capture_output=True)
    write_json(ROOT / "reports" / "round06_restore_drill.json", res)
    return res


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--next-date", required=True)
    ap.add_argument("--team-id", default="TEAM_REHEARSAL")
    a = ap.parse_args(argv)
    r = drill(Path(a.state), a.next_date, a.team_id)
    print(json.dumps(r, indent=1, ensure_ascii=False, default=str))
    return 0 if r.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
