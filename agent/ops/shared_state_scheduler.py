"""Issue #65: make every scheduled run observable from GitHub (shared-state branch), not only from the local terminal.

The 19:30 / 17:00 wrappers call this at the START (heartbeat: scheduled vs actual start, delay) and at the END (status JSON of the run,
whatever the outcome incl. BLOCKED / FAILED) so a late, blocked or failed run is visible even when no FINAL exists. Redacted whitelist only
(no absolute paths / user names). Never raises, never touches the submission flow.

  python -m agent.ops.shared_state_scheduler --task dryrun_1930 --event START
  python -m agent.ops.shared_state_scheduler --task dryrun_1930 --event END
  python -m agent.ops.shared_state_scheduler --task evaluation_1700 --event END
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

from agent.ops import shared_state_sync as S

REL = "shared_state/scheduler"
SOURCES = {"dryrun_1930": "logs/scheduled/latest_status.json", "evaluation_1700": "logs/evaluation/latest_status.json"}
SCHEDULED = {"dryrun_1930": "19:30", "evaluation_1700": "17:00"}
KEEP = ("status", "blocked_reason", "error_message", "scheduled_time", "actual_start_time", "started_at", "finished_at", "run_delay_minutes",
        "trade_date", "evaluation_date", "label", "network", "data_refresh", "etf_freshness", "quant", "active_share", "dplan_validation",
        "grounding", "market_data", "start_source", "settlement", "execution", "nav", "daily_return", "compliance", "prediction_sha256",
        "overall_status", "final_candidate")


def _clean(v):
    if isinstance(v, str):
        return re.sub(r"[A-Za-z]:\\\\?[^\s\"']*", "<path>", v)[:300]
    return v


def build(task: str, event: str, root: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now().astimezone()
    doc = {"task": task, "event": event, "recorded_at": now.isoformat(timespec="seconds"), "scheduled_local": SCHEDULED.get(task)}
    if event == "START":
        h, m = (int(x) for x in SCHEDULED[task].split(":"))
        sched = now.replace(hour=h, minute=m, second=0, microsecond=0)
        doc["actual_start_time"] = now.isoformat(timespec="seconds")
        doc["run_delay_minutes"] = max(0, int((now - sched).total_seconds() // 60))
        doc["status"] = "RUNNING"
        return doc
    p = root / SOURCES[task]
    try:
        src = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        doc["status"] = "STATUS_FILE_MISSING"
        return doc
    doc.update({k: _clean(src[k]) for k in KEEP if k in src})
    doc["trade_date_key"] = src.get("trade_date") or src.get("evaluation_date")
    return doc


def publish(task: str, event: str, root=None, *, push: bool = True) -> dict:
    try:
        root = S._root(root)
        doc = build(task, event, root)
        wt = S.ensure_worktree(root)
        base = wt / REL
        base.mkdir(parents=True, exist_ok=True)
        day = time.strftime("%Y-%m-%d")
        ga = wt / ".gitattributes"
        if not ga.exists() or "shared_state/** -text" not in ga.read_text(encoding="utf-8"):
            ga.write_text((ga.read_text(encoding="utf-8") if ga.exists() else "") + "shared_state/** -text" + chr(10), encoding="utf-8", newline=chr(10))
        for name in (f"{day}_{task}.json", f"latest_{task}.json"):
            (base / name).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + chr(10), encoding="utf-8", newline=chr(10))
        S._git(wt, "add", "-A", REL, ".gitattributes")
        if S._git(wt, "diff", "--cached", "--quiet", check=False).returncode != 0:
            S._git(wt, "commit", "-q", "-m", f"shared-state: scheduler {task} {event} {doc.get('status')}"
                   + "\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>")
        if push:
            for _ in range(S.PUSH_ATTEMPTS):
                if S._git(wt, "push", "-u", "origin", S.BRANCH, check=False).returncode == 0:
                    break
                S._git(wt, "pull", "--rebase", "origin", S.BRANCH, check=False)
            else:
                return {"status": "SYNC_PENDING", "detail": "push failed"}
        return {"status": "PUBLISHED", "task": task, "event": event, "doc_status": doc.get("status")}
    except Exception as e:  # noqa: BLE001  observability only
        return {"status": "SYNC_PENDING", "detail": f"{type(e).__name__}: {e}"[:300]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Publish scheduler run status to shared-state (Issue #65)")
    ap.add_argument("--task", required=True, choices=sorted(SOURCES))
    ap.add_argument("--event", required=True, choices=("START", "END"))
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(publish(a.task, a.event, push=not a.no_push), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
