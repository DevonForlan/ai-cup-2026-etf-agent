"""LOCAL Quant v1 freeze regression (needs the local market-data store data/history; not runnable on CI).

    .venv\\Scripts\\python.exe scripts\\ci\\local_freeze_regression.py

Re-runs W5 (2026-08-28, 24 trading days) with the frozen config and compares against the reference run
sim_runs/round06_baseline_quant_v1: final NAV 1,014,240,575.839861741934859718 and all 24 decision_core_hashes.
Also checks the strategy sha256 and that frozen paths have no uncommitted diff. Paste the output into the PR.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
FROZEN_SHA = "f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0"
W5_NAV = "1014240575.839861741934859718"
REF = ROOT / "sim_runs" / "round06_baseline_quant_v1"
FROZEN_PATHS = ["config/strategy_quant_v1.yaml", "agent/features", "agent/portfolio", "agent/pipeline.py",
                "agent/run_sim.py", "agent/sim"]


def main() -> int:
    from agent.ops.fingerprint import decision_core_hash
    from agent.run_sim import simulate
    sha = hashlib.sha256((ROOT / "config" / "strategy_quant_v1.yaml").read_bytes()).hexdigest()
    run_id = "local_freeze_regression_w5"
    s = simulate("2026-08-28", days=24, history=ROOT / "data" / "history", cfg_path="config/strategy_quant_v1.yaml",
                 method="B0_score_tiered", run_id=run_id, quiet=True, narrative="template")

    def hashes(d: Path) -> dict:
        return {os.path.basename(f): decision_core_hash(json.load(open(f, encoding="utf-8")))
                for f in sorted(glob.glob(str(d / "dplan" / "*.json")))}
    a, b = hashes(REF), hashes(ROOT / "sim_runs" / run_id)
    same = sum(a[k] == b.get(k) for k in a)
    diff = subprocess.run(["git", "diff", "--quiet", "--"] + FROZEN_PATHS, cwd=ROOT).returncode == 0
    nav = str(s["final_nav"])
    res = {"strategy_sha256": sha, "strategy_sha256_ok": sha == FROZEN_SHA, "w5_nav": nav,
           "w5_nav_ok": nav == W5_NAV, "decision_hashes": f"{same}/{len(a)}",
           "decision_hashes_ok": len(a) == 24 and same == 24 and len(b) == 24, "frozen_paths_no_diff": diff}
    ok = all(v for k, v in res.items() if k.endswith("_ok")) and diff
    for k, v in res.items():
        print(f"{k:24s} {v}")
    print("LOCAL_QUANT_FREEZE_REGRESSION =", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
