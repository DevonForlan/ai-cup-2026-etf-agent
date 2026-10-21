"""Quant v1 freeze check that runs on a hosted CI runner (no market data needed).

    python scripts/ci/quant_freeze_check.py [--base origin/master]

1. config/strategy_quant_v1.yaml sha256 must equal the frozen value (config/ops.yaml freeze.strategy_sha256).
2. Forbidden-change detection vs the PR base: any change under FROZEN_PATHS fails unless the PR carries the
   Owner-applied label `owner-approved-investment-change` (env OWNER_APPROVED_INVESTMENT_CHANGE=true).
   Changes under PROTECTED_PATHS only produce a warning (operational / schema code that feeds the D-Plan).
The W5 NAV (1,014,240,575.839861741934859718) and the 24 decision hashes need the local market-data store
(data/history, intentionally not in the repository): run scripts/ci/local_freeze_regression.py locally and
paste its output into the PR.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FROZEN_SHA = "f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0"
FROZEN_PATHS = ("config/strategy_quant_v1.yaml", "agent/features/", "agent/portfolio/", "agent/pipeline.py",
                "agent/run_sim.py", "agent/sim/")
PROTECTED_PATHS = ("agent/engine/", "agent/dplan/", "agent/competition_day.py", "config/competition.yaml")


def changed_files(base: str) -> list[str] | None:
    r = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"::warning::cannot diff against {base}: {r.stderr.strip()[:200]}")
        return None
    return [x.strip().replace("\\", "/") for x in r.stdout.splitlines() if x.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None)
    a = ap.parse_args(argv)
    ok = True
    sha = hashlib.sha256((ROOT / "config" / "strategy_quant_v1.yaml").read_bytes()).hexdigest()
    print(f"strategy_quant_v1.yaml sha256 {sha} {'== FROZEN' if sha == FROZEN_SHA else '!= FROZEN ' + FROZEN_SHA}")
    ok &= sha == FROZEN_SHA
    import yaml
    ops = yaml.safe_load((ROOT / "config" / "ops.yaml").read_text(encoding="utf-8"))
    pinned = str(ops["freeze"]["strategy_sha256"]).replace("sha256:", "")
    print(f"config/ops.yaml freeze.strategy_sha256 {'consistent' if pinned == FROZEN_SHA else 'MISMATCH ' + pinned}")
    ok &= pinned == FROZEN_SHA
    if a.base:
        files = changed_files(a.base)
        if files is not None:
            frozen = [f for f in files if f.startswith(FROZEN_PATHS)]
            protected = [f for f in files if f.startswith(PROTECTED_PATHS)]
            approved = os.environ.get("OWNER_APPROVED_INVESTMENT_CHANGE", "").lower() == "true"
            print(f"changed files vs {a.base}: {len(files)}; frozen-path changes: {frozen or 'none'}")
            for f in protected:
                print(f"::warning file={f}::protected path changed (operational / D-Plan code) - state D-Plan impact in the PR")
            if frozen and not approved:
                print("::error::frozen Quant path changed without the Owner label owner-approved-investment-change")
                ok = False
            elif frozen:
                print("frozen-path change carries the Owner label: a local W5 / 24-hash regression is REQUIRED in the PR")
    print("QUANT_FREEZE_CHECK =", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
