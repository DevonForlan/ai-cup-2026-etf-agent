"""Competition-state backup / restore (Round 06).

  python agent\\ops\\backup.py backup [--dest backups]            -> backups\\competition_state_<ts>.zip
  python agent\\ops\\backup.py restore --zip <file> --target <dir>  (never overwrites existing files)
  python agent\\ops\\backup.py verify --zip <file>

Included (small, irreplaceable operational state): config/*.yaml, data/settlement, data/observations,
submissions, archive manifests (ARCHIVE_MANIFEST.json only), audit, logs/ops, reports/ops_daily, templates.
Excluded: .env / any API key, data/history and data/raw (re-fetchable, large), full archives, sim_runs.
Every file is listed with sha256 in BACKUP_MANIFEST.json inside the zip; restore re-verifies every hash.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.ops.common import TPE, load_ops_config, ops_path, sha256_bytes, sha256_file  # noqa: E402

EXCLUDE = [".env", "*.env", ".env.*", "*secret*", "*.key", "*.pem"]


def _sources(ops_cfg: dict, base: Path) -> list[tuple[Path, str]]:
    """(absolute file, archive name relative to `base`)."""
    out = []

    def add_tree(p: Path, pattern: str = "*"):
        if p.exists():
            for f in sorted(p.rglob(pattern)):
                if f.is_file():
                    out.append(f)
    add_tree(ROOT / "config", "*.yaml")
    add_tree(ROOT / "templates")
    add_tree(ops_path(ops_cfg, "settlement_dir"))
    add_tree(ops_path(ops_cfg, "first_seen_ledger").parent)
    add_tree(ops_path(ops_cfg, "submissions_dir"))
    add_tree(ops_path(ops_cfg, "archive_dir"), "ARCHIVE_MANIFEST.json")
    add_tree(ops_path(ops_cfg, "ops_logs_dir"))
    if "ops_reports_dir" in ops_cfg["paths"]:
        add_tree(ops_path(ops_cfg, "ops_reports_dir"))
    add_tree(base / "audit")
    res = []
    for f in out:
        if any(fnmatch.fnmatch(f.name.lower(), pat) for pat in EXCLUDE):
            continue
        try:
            rel = f.relative_to(base)
        except ValueError:
            rel = Path("_config") / f.relative_to(ROOT)
        res.append((f, rel.as_posix()))
    return res


def backup(dest: Path | None = None, *, ops_cfg: dict | None = None, base: Path | None = None) -> Path:
    ops_cfg = ops_cfg or load_ops_config()
    base = base or ROOT
    dest = dest or ROOT / "backups"
    dest.mkdir(parents=True, exist_ok=True)
    z = dest / f"competition_state_{datetime.now(TPE):%Y%m%d_%H%M%S}.zip"
    if z.exists():
        raise FileExistsError(z)
    from agent.ops.preflight import git_info
    files = _sources(ops_cfg, base)
    manifest = {"created_at": datetime.now(TPE).isoformat(), "git": git_info(), "base": str(base),
                "files": [{"path": rel, "sha256": sha256_file(f), "size": f.stat().st_size} for f, rel in files],
                "excluded": ["data/history", "data/raw", ".env", "archive payloads", "logs/llm", "sim_runs"]}
    tmp = z.with_suffix(".zip.partial")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for f, rel in files:
            zf.write(f, rel)
        zf.writestr("BACKUP_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    tmp.replace(z)
    return z


def verify(zpath: Path) -> list[str]:
    probs = []
    with zipfile.ZipFile(zpath) as zf:
        m = json.loads(zf.read("BACKUP_MANIFEST.json"))
        names = set(zf.namelist())
        for f in m["files"]:
            if f["path"] not in names:
                probs.append(f"missing {f['path']}")
            elif sha256_bytes(zf.read(f["path"])) != f["sha256"]:
                probs.append(f"hash mismatch {f['path']}")
        for n in names:
            if any(fnmatch.fnmatch(Path(n).name.lower(), pat) for pat in EXCLUDE):
                probs.append(f"excluded file present {n}")
    return probs


def restore(zpath: Path, target: Path) -> dict:
    probs = verify(zpath)
    if probs:
        raise RuntimeError("backup verification failed: " + "; ".join(probs[:5]))
    target.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(zpath) as zf:
        m = json.loads(zf.read("BACKUP_MANIFEST.json"))
        for f in m["files"]:
            dst = target / f["path"]
            if dst.exists():
                raise FileExistsError(f"restore refuses to overwrite {dst}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(zf.read(f["path"]))
            if sha256_file(dst) != f["sha256"]:
                raise RuntimeError(f"restored file hash mismatch {dst}")
            n += 1
    return {"restored_files": n, "target": str(target), "git": m.get("git"), "created_at": m.get("created_at")}


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["backup", "restore", "verify"])
    ap.add_argument("--dest", default=None)
    ap.add_argument("--zip", default=None)
    ap.add_argument("--target", default=None)
    a = ap.parse_args(argv)
    if a.action == "backup":
        z = backup(Path(a.dest) if a.dest else None)
        print("BACKUP:", z, "verify:", verify(z) or "OK")
    elif a.action == "verify":
        p = verify(Path(a.zip))
        print("VERIFY:", p or "OK")
        return 0 if not p else 2
    else:
        print(json.dumps(restore(Path(a.zip), Path(a.target)), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
