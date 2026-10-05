"""Runtime of run_day for: quant-only, LLM narrative, full LLM (events + bounded signal), using the mock
provider with an artificial per-call latency to emulate a remote API. Reports p50 / p95 over N days.

  python agent\\tools\\llm_runtime_benchmark.py --start 2026-09-15 --days 10 --latency 3
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT, load_yaml  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.engine.rules import load_rulebook  # noqa: E402
from agent.llm.client import load_llm_config, make_provider  # noqa: E402
from agent.pipeline import run_day  # noqa: E402
from agent.sim.calendar import TradingCalendar  # noqa: E402
from agent.sim.models import Settlement  # noqa: E402


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0.0


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-15")
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--latency", type=float, default=3.0)
    a = ap.parse_args(argv)
    rb = load_rulebook()
    st = HistoryStore()
    cal = TradingCalendar(st.dates("daily_prices"))
    days = [d for d in cal.days if d >= a.start][: a.days]
    cfg = load_yaml("config/strategy_quant_v1.yaml")
    modes = {"quant_only": None,
             "llm_narrative": {"narrative": {"mode": "llm"}},
             "full_llm": {"narrative": {"mode": "llm"}, "events": {"enabled": True},
                          "llm_signal": {"enabled": True, "max_percentile_adjustment": 5}}}
    modes["full_llm"]["events"]["cache"] = False
    res = {}
    for name, over in modes.items():
        times, calls = [], []
        for d in days:
            llm = None
            if over:
                lc = load_llm_config()
                lc.update({"provider": "mock", "mock_latency": a.latency, "log_calls": False})
                for k, v in over.items():
                    lc[k].update(v)
                llm = {"cfg": lc, "provider": make_provider(lc), "log_root": None}
            t0 = time.perf_counter()
            r = run_day(d, st, Settlement.initial("x", rb.rules.initial_cash), rb, cfg, team_id="TEAM_BENCH",
                        out_dir=ROOT / "logs" / "runtime" / "llm_bench", log_dir=ROOT / "logs" / "runtime" / "llm_bench",
                        calendar=cal, light=True, llm=llm)
            times.append(time.perf_counter() - t0)
            calls.append(r.llm_summary.get("calls", 0))
            assert r.validation.ok
        res[name] = {"p50_sec": round(pct(times, 0.5), 2), "p95_sec": round(pct(times, 0.95), 2),
                     "max_sec": round(max(times), 2), "llm_calls_per_day": sum(calls) / len(calls)}
        print(name, res[name], flush=True)
    out = {"simulated_latency_per_call_sec": a.latency, "days": days, "results": res,
           "note": "mock provider with sleep(latency) per call; real latency depends on provider/model"}
    (ROOT / "reports" / "round04_runtime.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
