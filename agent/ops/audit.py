"""Build the audit/ evidence tree (hashes + manifests + pointers; raw data is NOT copied).

  audit/README.md
  audit/architecture/INDEX.md         links to the architecture docs + module list with sha256
  audit/prompts/PROMPTS.json          prompt files, versions, sha256
  audit/configs/CONFIGS.json          config files sha256 (+ freeze record)
  audit/runs/RUNS.json                index of archive/YYYYMMDD/<run_id>/ARCHIVE_MANIFEST.json (hash of each)

  python agent\\ops\\audit.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.ops.common import TPE, load_ops_config, ops_path, sha256_file, write_json  # noqa: E402
from agent.ops.preflight import git_info, prompt_versions  # noqa: E402

ARCH_DOCS = ["research/07_AGENT_ARCHITECTURE_RECOMMENDATION.md", "agent/README.md", "DEVELOPMENT_STATUS.md",
             "docs/COMPETITION_DAILY_RUNBOOK.md", "docs/EMERGENCY_RUNBOOK.md", "docs/AGENT_AUTONOMY_EVIDENCE.md",
             "docs/STRATEGY_FREEZE_RECORD.md"]


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def build_audit(out: Path | None = None, ops_cfg: dict | None = None) -> Path:
    ops_cfg = ops_cfg or load_ops_config()
    out = out or ROOT / "audit"
    now = datetime.now(TPE).isoformat()
    g = git_info()
    # architecture
    mods = sorted(p for p in (ROOT / "agent").rglob("*.py") if "__pycache__" not in p.parts)
    lines = ["# Architecture index", "", f"generated {now}, git:{g['sha']}", "", "## Documents", ""]
    lines += [f"- [{d}](../../{d})" + ("" if (ROOT / d).exists() else " (missing)") for d in ARCH_DOCS]
    lines += ["", "## Modules (sha256 prefix)", "", "| module | sha256 |", "|---|---|"]
    lines += [f"| {_rel(p)} | {sha256_file(p)[7:23]} |" for p in mods]
    (out / "architecture").mkdir(parents=True, exist_ok=True)
    (out / "architecture" / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # prompts
    pv = prompt_versions()
    write_json(out / "prompts" / "PROMPTS.json", {"generated_at": now, "prompts": [
        {"file": _rel(p), "version": pv.get(p.stem), "sha256": sha256_file(p)}
        for p in sorted((ROOT / "agent/llm/prompts").glob("*.txt"))]})
    # configs
    write_json(out / "configs" / "CONFIGS.json", {"generated_at": now, "freeze": ops_cfg.get("freeze"),
                                                  "configs": [{"file": _rel(p), "sha256": sha256_file(p)}
                                                              for p in sorted((ROOT / "config").glob("*.yaml"))]})
    # runs
    runs = []
    arch = ops_path(ops_cfg, "archive_dir")
    for m in sorted(arch.glob("*/*/ARCHIVE_MANIFEST.json")) if arch.exists() else []:
        j = json.loads(m.read_text(encoding="utf-8"))
        meta_p = m.parent / "package" / "run_metadata.json"
        meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
        runs.append({"trade_date": j["trade_date"], "run_id": j["run_id"], "mode": meta.get("mode"),
                     "manifest": m.relative_to(arch).as_posix(), "manifest_sha256": sha256_file(m),
                     "dplan_sha256": meta.get("dplan_sha256"), "git_sha": meta.get("git_sha"),
                     "files": len(j["files"])})
    write_json(out / "runs" / "RUNS.json", {"generated_at": now, "archive_root": "archive/", "runs": runs})
    (out / "README.md").write_text(
        "# Audit evidence\n\n"
        f"Generated {now} at git:{g['sha']} by `agent/ops/audit.py`. Regenerate any time; it never copies raw data.\n\n"
        "| folder | content |\n|---|---|\n"
        "| architecture/INDEX.md | architecture docs + every agent module with sha256 |\n"
        "| prompts/PROMPTS.json | prompt files, versions, sha256 |\n"
        "| configs/CONFIGS.json | every config/*.yaml sha256 + strategy freeze record |\n"
        f"| runs/RUNS.json | {len(runs)} archived runs: archive/YYYYMMDD/<run_id>/ARCHIVE_MANIFEST.json sha256 |\n\n"
        "Verification: re-hash a file and compare with the manifest; every archived D-Plan sha256 is in "
        "RUNS.json and in the run's package/manifest.json. Raw market data is referenced by the store manifest hash "
        "in each run's data_health.json / run_metadata.json (data_snapshot_hash), not copied.\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(build_audit())
