"""CI config / schema validation (no network, no market data).

    python scripts/ci/validate_configs.py

- every config/*.yaml parses; config/ops.yaml has the required operational keys and run_mode is valid
- every tracked *.schema*.json is a valid JSON Schema (Draft 2020-12)
- the official D-Plan v4.3 schema referenced by config/competition.yaml exists and validates the organiser
  examples of the same version
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    errors = []
    for p in sorted((ROOT / "config").glob("*.yaml")):
        try:
            yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            errors.append(f"{p.name}: YAML error {e}")
    ops = yaml.safe_load((ROOT / "config" / "ops.yaml").read_text(encoding="utf-8"))
    for k in ("paths", "freeze", "deadline", "run_mode", "team", "submission", "market_coverage"):
        if k not in ops:
            errors.append(f"ops.yaml: missing key {k}")
    if str(ops.get("run_mode")).upper() not in ("PRECOMPETITION", "COMPETITION"):
        errors.append(f"ops.yaml: invalid run_mode {ops.get('run_mode')}")
    files = subprocess.run(["git", "ls-files", "*.schema*.json", "**/*.schema*.json"], cwd=ROOT,
                           capture_output=True, text=True).stdout.split()
    for f in sorted(set(files)):
        try:
            jsonschema.Draft202012Validator.check_schema(json.loads((ROOT / f).read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{f}: invalid JSON Schema ({type(e).__name__}: {str(e)[:120]})")
    comp = yaml.safe_load((ROOT / "config" / "competition.yaml").read_text(encoding="utf-8"))
    sp = ROOT / comp["dplan"]["schema_path"]
    if not sp.exists():
        errors.append(f"D-Plan schema missing: {sp}")
    else:
        schema = json.loads(sp.read_text(encoding="utf-8"))
        v = jsonschema.Draft202012Validator(schema)
        for ex in sorted(sp.parent.glob("D-Plan_TEAM_*.json")):
            errs = list(v.iter_errors(json.loads(ex.read_text(encoding="utf-8"))))
            print(f"{ex.name}: {'valid' if not errs else str(len(errs)) + ' schema error(s)'} vs {sp.name}")
            if errs:
                errors.append(f"{ex.name} does not validate against {sp.name}")
    for e in errors:
        print("ERROR", e)
    print(f"config/schema validation: {len(errors)} error(s); schemas checked {len(set(files))}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
