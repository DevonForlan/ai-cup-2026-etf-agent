"""Cross-process lock files with SAFE stale-lock recovery (Round 06).

A lock file holds {"pid", "host", "created_at"}. A lock is only recovered when it is older than the
threshold AND its owner process no longer exists on this host; a lock whose owner is alive is never
removed (we wait / time out instead). Every recovery is appended to logs/ops/lock_recovery.jsonl.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

TPE = timezone(timedelta(hours=8))


class LockTimeout(TimeoutError):
    pass


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.GetLastError() == 5               # access denied -> exists
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259               # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock(lock: Path) -> dict | None:
    try:
        return json.loads(lock.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return {}                                           # empty / legacy lock file (no owner info)


def _audit(rec: dict, audit_log: Path | None) -> None:
    if audit_log is None:
        from agent.config import ROOT
        audit_log = ROOT / "logs" / "ops" / "lock_recovery.jsonl"
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def is_stale(lock: Path, stale_after: float) -> tuple[bool, str]:
    info = read_lock(lock)
    if info is None:
        return False, "missing"
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return False, "missing"
    if age < stale_after:
        return False, f"young ({age:.0f}s)"
    pid, host = info.get("pid"), info.get("host")
    if host and host != socket.gethostname():
        return False, f"owner on another host {host}"      # cannot verify -> never steal
    if pid and pid_alive(int(pid)):
        return False, f"owner pid {pid} alive"
    return True, f"age {age:.0f}s, owner pid {pid or 'unknown'} not running"


def recover_stale(lock: Path, stale_after: float, audit_log: Path | None = None) -> bool:
    stale, why = is_stale(lock, stale_after)
    if not stale:
        return False
    info = read_lock(lock)
    dst = lock.with_name(lock.name + f".stale-{datetime.now(TPE):%Y%m%d_%H%M%S}-{os.getpid()}")
    try:
        os.replace(lock, dst)                               # keep the evidence instead of deleting it
    except OSError:
        return False
    _audit({"at": datetime.now(TPE).isoformat(), "lock": str(lock), "moved_to": dst.name, "reason": why,
            "owner": info, "recovered_by_pid": os.getpid()}, audit_log)
    return True


class FileLock:
    def __init__(self, lock: Path, timeout: float = 60.0, stale_after: float = 120.0, audit_log: Path | None = None):
        self.lock, self.timeout, self.stale_after, self.audit_log = Path(lock), timeout, stale_after, audit_log
        self.fd = None

    def acquire(self) -> "FileLock":
        t0 = time.time()
        while True:
            try:
                self.fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, json.dumps({"pid": os.getpid(), "host": socket.gethostname(),
                                              "created_at": datetime.now(TPE).isoformat()}).encode())
                return self
            except FileExistsError:
                if recover_stale(self.lock, self.stale_after, self.audit_log):
                    continue
                if time.time() - t0 > self.timeout:
                    raise LockTimeout(f"{self.lock} held: {is_stale(self.lock, self.stale_after)[1]}")
                time.sleep(0.05)

    def release(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
            try:
                os.remove(self.lock)
            except OSError:
                pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *a):
        self.release()


def find_locks(root: Path) -> list[Path]:
    return [p for p in Path(root).rglob("*.lock") if p.is_file()]
