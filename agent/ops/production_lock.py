"""Single-run protection for COMPETITION production runs (Issue #20).

The 19:30 prediction (agent/ops/scheduled_run.py) and the 07:30 morning FINAL (agent/ops/morning_final.py) both
write the day's shared state (logs/ops/<ymd>, submissions/<ymd>, FINAL history, receipts). They never run at the same
time: each takes this lock first and, if another run holds it beyond `wait_s`, stops with LOCK_UNAVAILABLE (fail
closed: no decision, no FINAL, no upload). A lock whose owner process is gone is recovered (agent/data/locks.py;
the stale file is kept as evidence). The 17:00 evaluation does not take it: it writes only the paper-evaluation
ledger, never FINAL / submission state.
"""
from __future__ import annotations

from pathlib import Path

LOCK_NAME = "competition_production.lock"


def production_lock(locks_dir: Path, *, wait_s: float, stale_after_s: float = 120.0):
    from agent.data.locks import FileLock
    locks_dir = Path(locks_dir)
    locks_dir.mkdir(parents=True, exist_ok=True)
    return FileLock(locks_dir / LOCK_NAME, timeout=wait_s, stale_after=stale_after_s,
                    audit_log=locks_dir / "lock_audit.jsonl")
