"""Run-time benchmark of the deterministic core (one run_daily equivalent).

  python agent\\tools\\benchmark.py --date 2026-10-02 [--config config\\strategy_quant_v1.yaml]

Reports wall time per stage (cold = no feature cache, warm = cached), CPU time and peak RSS."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT, load_strategy  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.engine.rules import load_rulebook  # noqa: E402
from agent.pipeline import run_day  # noqa: E402
from agent.sim.models import Settlement  # noqa: E402


def peak_rss_mb() -> float | None:
    if os.name != "nt":
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    c = PMC()
    c.cb = ctypes.sizeof(PMC)
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = wintypes.HANDLE
    ctypes.windll.psapi.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.PeakWorkingSetSize / 2**20


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-10-02")
    ap.add_argument("--config", default="config/strategy.yaml")
    a = ap.parse_args(argv)
    t_imp = time.perf_counter()
    cfg = load_strategy(a.config)
    rb = load_rulebook()
    st = HistoryStore()
    t_load0 = time.perf_counter()
    for t in ("daily_prices", "institutional", "monthly_revenue", "market_overnight", "etf_holdings"):
        st.load(t)
    t_load = time.perf_counter() - t_load0
    s0 = Settlement.initial("x", rb.rules.initial_cash)
    out = ROOT / "logs" / "runtime" / "benchmark"
    cpu0 = time.process_time()
    w0 = time.perf_counter()
    cold = run_day(a.date, st, s0, rb, cfg, team_id="TEAM_BENCH", out_dir=out, log_dir=out, use_cache=False)
    cold_wall = time.perf_counter() - w0
    warm = run_day(a.date, st, s0, rb, cfg, team_id="TEAM_BENCH", out_dir=out, log_dir=out)
    res = {"date": a.date, "machine": platform.processor(), "cpu_count": os.cpu_count(),
           "python": platform.python_version(), "data_load_sec": round(t_load, 3),
           "cold_stage_sec": {k: round(v, 3) for k, v in cold.timings.items()},
           "cold_wall_sec_incl_logs": round(cold_wall, 3),
           "warm_stage_sec": {k: round(v, 3) for k, v in warm.timings.items()},
           "cpu_sec_total": round(time.process_time() - cpu0, 3), "peak_rss_mb": round(peak_rss_mb() or 0, 1),
           "total_incl_startup_sec": round(time.perf_counter() - t_imp, 3), "validation_ok": cold.validation.ok}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "runtime_benchmark.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
