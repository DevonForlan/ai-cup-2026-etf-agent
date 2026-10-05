"""Soak test (Round 06): run the daily pipeline N times in ONE process and watch for degradation.

  python agent\\ops\\soak.py --iterations 100 [--store fixture|real]

Each iteration = competition_day (dry-run) for the same trade date with the clock advanced 1 minute (new run_id).
Every 7th iteration crashes on purpose (SimulatedCrash at a rotating phase) to exercise recovery under load.
Checks per iteration: status, validation, decision fingerprint == iteration 1, FINAL sha256 unchanged (frozen),
candidate package + archive hashes intact, no new .partial leftovers except crashed runs, no lock files left.
Metrics: runtime, RSS memory, open handles (Windows), archive count, temp files.
Outputs: reports/round06_soak.csv, reports/round06_soak_summary.json.
"""
from __future__ import annotations

import argparse
import copy
import csv
import gc
import json
import os
import statistics
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.ops.common import Clock, load_ops_config, sha256_file, write_json  # noqa: E402


def rss_mb() -> float | None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return c.WorkingSetSize / 2**20
        return None
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except Exception:  # noqa: BLE001
        return None


def open_handles() -> int | None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        n = wintypes.DWORD()
        if k32.GetProcessHandleCount(k32.GetCurrentProcess(), ctypes.byref(n)):
            return n.value
        return None
    try:
        return len(os.listdir(f"/proc/{os.getpid()}/fd"))
    except OSError:
        return None


def soak(iterations: int = 100, *, store_kind: str = "fixture", root: Path | None = None, out_dir: Path | None = None,
         quiet: bool = False) -> dict:
    from agent.competition_day import SimulatedCrash, run_competition_day
    from agent.data.locks import find_locks
    from agent.data.loaders import HistoryStore, load_fixture_store
    from agent.ops.archive_run import partial_dirs, verify_archive
    from agent.ops.package_submission import active_final, verify_package
    root = root or Path(tempfile.mkdtemp(prefix="soak_"))
    ops_cfg = copy.deepcopy(load_ops_config())
    for i, k in enumerate(ops_cfg["paths"]):
        ops_cfg["paths"][k] = str(root / f"{k[:3]}{i}")
    if store_kind == "fixture":
        store = load_fixture_store(ROOT / "tests" / "fixtures" / "synthetic", root / "store")
        trade_date, t0clock, fixture = "2026-10-26", "2026-10-25T19:30:00+08:00", True
    else:
        store = HistoryStore()
        trade_date, t0clock, fixture = "2026-10-02", "2026-10-01T19:30:00+08:00", False
    git = {"sha": "soak", "branch": "master", "dirty_paths": []}
    phases = ["after_refresh", "before_package", "package_mid", "before_archive", "archive_mid"]
    rows, fp0, final0, crashes = [], None, None, 0
    base_clock = Clock(t0clock)
    for it in range(1, iterations + 1):
        gc.collect()
        clk = Clock(base_clock.now() + timedelta(minutes=it - 1))
        crash_at = phases[(it // 7) % len(phases)] if it % 7 == 0 else None

        def hook(name, _c=crash_at):
            if name == _c:
                raise SimulatedCrash(name)
        t = time.perf_counter()
        err, s = "", {}
        try:
            s = run_competition_day(trade_date, "TEAM_SOAK", "dry-run", store=store, store_is_fixture=fixture,
                                    ops_cfg=ops_cfg, clock=clk, git=git, archive_readonly=False, skip_refresh=True,
                                    initial=True, crash_hook=hook, write_report=False)
        except SimulatedCrash as e:
            crashes += 1
            err = f"SIMULATED_CRASH:{e}"
        except Exception as e:  # noqa: BLE001
            err = f"UNEXPECTED {type(e).__name__}: {e}"
        dt = time.perf_counter() - t
        fin = active_final(trade_date, ops_cfg)
        problems = []
        if not err:
            if s.get("status") != "DRY_RUN_OK":
                problems.append(f"status {s.get('status')}")
            if s.get("validation") != "PASS":
                problems.append("validation")
            fp0 = fp0 or s.get("decision_fingerprint")
            if s.get("decision_fingerprint") != fp0:
                problems.append("fingerprint drift")
            if s.get("package") and verify_package(Path(s["package"])):
                problems.append("package corrupted")
            if s.get("archive") and verify_archive(Path(s["archive"])):
                problems.append("archive corrupted")
        if fin:
            final0 = final0 or fin["sha256"]
            ff = Path(ops_cfg["paths"]["submissions_dir"]) / trade_date.replace("-", "") / "FINAL" / fin["file"]
            if fin["sha256"] != final0 or sha256_file(ff) != final0:
                problems.append("FINAL changed / corrupted")
        arch_dir = Path(ops_cfg["paths"]["archive_dir"]) / trade_date.replace("-", "")
        rows.append({"iteration": it, "runtime": round(dt, 3), "rss_mb": round(rss_mb() or 0, 1),
                     "open_handles": open_handles(), "archive_count": len([p for p in arch_dir.iterdir()
                                                                          if not p.name.startswith(".")]) if arch_dir.exists() else 0,
                     "partial_dirs": len(partial_dirs(ops_cfg)), "lock_files": len(find_locks(root)),
                     "errors": err if err.startswith("UNEXPECTED") else "", "simulated_crash": crash_at or "",
                     "warnings": len((s.get("preflight") or {}).get("warns", [])), "status": s.get("status", "CRASHED"),
                     "validation": s.get("validation", ""), "hash_consistent": "fingerprint drift" not in problems
                     and "FINAL changed / corrupted" not in problems, "problems": "; ".join(problems)})
        if not quiet and (it % 10 == 0 or problems or err.startswith("UNEXPECTED")):
            r = rows[-1]
            print(f"iter {it:3d} {r['status']:12s} {r['runtime']:6.2f}s rss={r['rss_mb']}MB handles={r['open_handles']} "
                  f"archives={r['archive_count']} partial={r['partial_dirs']} {r['problems'] or r['errors']}", flush=True)
    rss = [r["rss_mb"] for r in rows if r["rss_mb"]]
    rt = sorted(r["runtime"] for r in rows if not r["simulated_crash"])
    hd = [r["open_handles"] for r in rows if r["open_handles"] is not None]
    warm = rss[min(4, len(rss) - 1):] if rss else []
    growth = (warm[-1] - warm[0]) if len(warm) > 1 else 0.0
    mem_flag = "WARN" if warm and (growth > 150 or growth > 0.5 * warm[0]) else "PASS"
    summ = {"iterations": iterations, "store": store_kind, "root": str(root), "simulated_crashes": crashes,
            "unexpected_exceptions": sum(1 for r in rows if r["errors"]),
            "iterations_with_problems": sum(1 for r in rows if r["problems"]),
            "corrupted_outputs": sum(1 for r in rows if "corrupted" in r["problems"]),
            "illegal_overwrite": sum(1 for r in rows if "FINAL changed" in r["problems"]),
            "fingerprint_drift": sum(1 for r in rows if "fingerprint drift" in r["problems"]),
            "stale_locks_left": rows[-1]["lock_files"] if rows else 0,
            "partial_dirs_left": rows[-1]["partial_dirs"] if rows else 0,
            "partial_dirs_expected_max": crashes,
            "rss_mb": {"start": rss[0] if rss else None, "median": statistics.median(rss) if rss else None,
                       "max": max(rss) if rss else None, "end": rss[-1] if rss else None,
                       "warm_growth_mb": round(growth, 1), "flag": mem_flag},
            "handles": {"start": hd[0] if hd else None, "max": max(hd) if hd else None, "end": hd[-1] if hd else None},
            "runtime_sec": {"p50": rt[len(rt) // 2] if rt else None, "p95": rt[min(len(rt) - 1, int(0.95 * len(rt)))] if rt else None,
                            "first10_median": statistics.median(rt[:10]) if rt else None,
                            "last10_median": statistics.median(sorted(r["runtime"] for r in rows[-10:]
                                                                      if not r["simulated_crash"])) if rt else None},
            "archive_count_end": rows[-1]["archive_count"] if rows else 0}
    summ["passed"] = (summ["unexpected_exceptions"] == 0 and summ["iterations_with_problems"] == 0
                      and summ["stale_locks_left"] == 0 and summ["partial_dirs_left"] <= crashes)
    out_dir = out_dir or ROOT / "reports"
    with open(out_dir / "round06_soak.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    write_json(out_dir / "round06_soak_summary.json", summ)
    return summ


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=100)
    ap.add_argument("--store", choices=["fixture", "real"], default="fixture")
    a = ap.parse_args(argv)
    s = soak(a.iterations, store_kind=a.store)
    print(json.dumps(s, indent=1))
    return 0 if s["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
