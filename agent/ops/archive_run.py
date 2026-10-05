"""Immutable run archive: archive/YYYYMMDD/<run_id>/ (refuses to overwrite; reruns get a new run_id).

Contains the candidate package, config snapshots, ops logs (data health / preflight / reconciliation /
competition_day log), the day's LLM call log, and an archive manifest with sha256 of every file.
Large raw data is NOT copied: it is referenced by path + hash (raw manifest, store manifest hash).
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from agent.config import ROOT
from agent.ops.common import TPE, load_ops_config, ops_path, sha256_file, write_json, ymd


def run_id_for(clock_now: datetime, git_sha: str) -> str:
    return f"{clock_now:%Y%m%d_%H%M%S}_{git_sha.replace('git:', 'git').replace('-dirty', '-dirty')}"


def archive_run(trade_date: str, run_id: str, *, package_dir: Path, config_files: list[str],
                extra_files: list[Path] | None = None, ops_cfg: dict | None = None, readonly: bool = True) -> Path:
    ops_cfg = ops_cfg or load_ops_config()
    root = ops_path(ops_cfg, "archive_dir") / ymd(trade_date) / run_id
    if root.exists():
        raise FileExistsError(f"archive {root} exists; archives are immutable")
    (root / "package").mkdir(parents=True)
    for p in package_dir.iterdir():
        if p.is_file():
            shutil.copy2(p, root / "package" / p.name)
    (root / "config").mkdir()
    for c in config_files:
        src = ROOT / c
        if src.exists():
            shutil.copy2(src, root / "config" / src.name)
    (root / "ops_logs").mkdir()
    logs = ops_path(ops_cfg, "ops_logs_dir") / ymd(trade_date)
    if logs.exists():
        for p in logs.iterdir():
            if p.is_file():
                shutil.copy2(p, root / "ops_logs" / p.name)
    llm = ROOT / "logs" / "llm" / ymd(trade_date) / "calls.jsonl"
    if llm.exists():
        (root / "llm").mkdir()
        shutil.copy2(llm, root / "llm" / "calls.jsonl")
    for p in extra_files or []:
        if Path(p).exists():
            shutil.copy2(p, root / Path(p).name)
    files = sorted(p for p in root.rglob("*") if p.is_file())
    write_json(root / "ARCHIVE_MANIFEST.json", {
        "trade_date": trade_date, "run_id": run_id, "archived_at": datetime.now(TPE).isoformat(),
        "files": [{"path": str(p.relative_to(root)).replace("\\", "/"), "sha256": sha256_file(p),
                   "size": p.stat().st_size} for p in files]})
    for p in root.rglob("*") if readonly else []:   # best-effort read-only flag (Windows: attribute R)
        if p.is_file():
            try:
                p.chmod(0o444)
            except OSError:
                pass
    return root
