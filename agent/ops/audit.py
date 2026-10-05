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
             "docs/STRATEGY_FREEZE_RECORD.md", "docs/OFFICIAL_SETTLEMENT_ENTRY_SOP.md", "docs/COMPETITION_CODE_FREEZE.md",
             "docs/FINAL_OPERATOR_CHECKLIST.md", "reports/DATA_AVAILABILITY_MATRIX.md"]


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
    # settlement ledger (internal / official / confirmation / reconciliation), packages, submission states
    sdir = ops_path(ops_cfg, "settlement_dir")
    led = [{"file": f.name, "sha256": sha256_file(f)} for f in sorted(sdir.glob("*.json"))] if sdir.exists() else []
    write_json(out / "settlement" / "LEDGER.json", {"generated_at": now, "settlement_dir": str(sdir), "files": led})
    sub = ops_path(ops_cfg, "submissions_dir")
    days = []
    for d in (sorted(p for p in sub.iterdir() if p.is_dir()) if sub.exists() else []):
        hist, st, fz = d / "final_history.jsonl", d / "submission_state.json", d / "FINAL_FREEZE.json"
        rc = d / "receipts.jsonl"
        days.append({"day": d.name,
                     "candidates": len([c for c in (d / "candidates").glob("*") if not c.name.startswith(".")])
                     if (d / "candidates").exists() else 0,
                     "final_history_sha256": sha256_file(hist) if hist.exists() else None,
                     "final_freeze": json.loads(fz.read_text(encoding="utf-8")) if fz.exists() else None,
                     "submission_state": json.loads(st.read_text(encoding="utf-8"))["state"] if st.exists() else "NOT_READY",
                     "receipts": len(rc.read_text(encoding="utf-8").splitlines()) if rc.exists() else 0})
    write_json(out / "submissions" / "SUBMISSIONS.json", {"generated_at": now, "days": days})
    from agent.submission.receipt import write_schema
    write_schema(out / "submissions" / "receipt.schema.json")
    comp = completeness(out, ops_cfg, g, runs, led, days)
    write_json(out / "COMPLETENESS.json", comp)
    (out / "README.md").write_text(
        "# Audit evidence\n\n"
        f"Generated {now} at git:{g['sha']} by `agent/ops/audit.py`. Regenerate any time; it never copies raw data.\n\n"
        "| folder | content |\n|---|---|\n"
        "| architecture/INDEX.md | architecture docs + every agent module with sha256 |\n"
        "| prompts/PROMPTS.json | prompt files, versions, sha256 |\n"
        "| configs/CONFIGS.json | every config/*.yaml sha256 + strategy freeze record |\n"
        f"| runs/RUNS.json | {len(runs)} archived runs: archive/YYYYMMDD/<run_id>/ARCHIVE_MANIFEST.json sha256 |\n"
        f"| settlement/LEDGER.json | {len(led)} settlement files (internal / official / confirmation / reconciliation) |\n"
        f"| submissions/SUBMISSIONS.json | {len(days)} trade dates: candidates, FINAL freeze, submission state, receipts |\n"
        "| submissions/receipt.schema.json | submission receipt JSON schema |\n"
        f"| COMPLETENESS.json | audit completeness checklist: {'PASS' if comp['passed'] else 'GAPS ' + str(comp['missing'])} |\n\n"
        "Verification: re-hash a file and compare with the manifest; every archived D-Plan sha256 is in "
        "RUNS.json and in the run's package/manifest.json. Raw market data is referenced by the store manifest hash "
        "in each run's data_health.json / run_metadata.json (data_snapshot_hash), not copied.\n", encoding="utf-8")
    return out


def completeness(out: Path, ops_cfg: dict, g: dict, runs: list, led: list, days: list) -> dict:
    fz = ops_cfg.get("freeze") or {}
    items = {
        "architecture": (out / "architecture" / "INDEX.md").exists(),
        "strategy_freeze": bool(fz) and sha256_file(ROOT / fz["strategy_config"]) == fz["strategy_sha256"]
        and (ROOT / "docs" / "STRATEGY_FREEZE_RECORD.md").exists(),
        "prompts": (out / "prompts" / "PROMPTS.json").exists(),
        "configs": (out / "configs" / "CONFIGS.json").exists(),
        "git_sha": bool(g.get("sha")),
        "daily_runs_archived": bool(runs),
        "settlement_ledger": any(x["file"].endswith("_internal.json") for x in led),
        "reconciliation": any(x["file"].endswith("_reconciliation.json") for x in led),
        "dplan_packages": any(d["candidates"] for d in days),
        "final_freeze_records": any(d["final_freeze"] for d in days),
        "receipt_schema": (out / "submissions" / "receipt.schema.json").exists(),
        "archive_manifests_verify": all(_verify_run(ops_cfg, r) for r in runs[-50:]),
    }
    return {"items": items, "passed": all(items.values()), "missing": [k for k, v in items.items() if not v]}


def _verify_run(ops_cfg: dict, r: dict) -> bool:
    from agent.ops.archive_run import verify_archive
    return not verify_archive(ops_path(ops_cfg, "archive_dir") / r["manifest"].rsplit("/", 1)[0])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(build_audit())
