"""Submission package + FINAL_CANDIDATE marking. NO upload: the submission mechanism is unconfirmed (NC-1).

Layout (per trade date):
  submissions/YYYYMMDD/candidates/<run_id>/   full package of one run (never overwritten)
  submissions/YYYYMMDD/FINAL/D-Plan_<team>_<date>.json   the ONLY file meant for manual upload
  submissions/YYYYMMDD/FINAL_CANDIDATE.txt      big banner: file, sha256, validation, team, date, git sha
  submissions/YYYYMMDD/final_history.jsonl      every FINAL marking (append-only)

A candidate is marked FINAL only if: validation PASS, team_id == expected, trade_date == expected,
filename == D-Plan_<team>_<date>.json, and the copied file's sha256 equals the validated file's sha256.
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from agent.config import ROOT
from agent.ops.common import TPE, load_ops_config, ops_path, sha256_file, write_json, ymd

BANNER = "=" * 72


def _validation_md(rep: dict) -> str:
    lines = [f"# Validation report — {'PASS' if rep['ok'] else 'FAIL'}", "", f"summary: {rep['summary']}", "",
             "| status | rule | message |", "|---|---|---|"]
    for c in rep["checks"]:
        lines.append(f"| {c['status']} | {c['rule_id']} | {str(c['message'])[:160].replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def build_package(day_result, *, team_id: str, trade_date: str, run_id: str, mode: str,
                  data_health: dict | None, reconciliation: dict | None, preflight: dict | None,
                  run_metadata: dict, ops_cfg: dict | None = None, extra_json: dict | None = None) -> Path:
    ops_cfg = ops_cfg or load_ops_config()
    root = ops_path(ops_cfg, "submissions_dir") / ymd(trade_date) / "candidates" / run_id
    if root.exists():
        raise FileExistsError(f"candidate {root} exists; packages are immutable (use a new run_id)")
    root.mkdir(parents=True)
    doc = day_result.doc
    fname = f"D-Plan_{team_id}_{trade_date}.json"
    shutil.copy2(day_result.dplan_path, root / fname)
    rep = day_result.validation.to_dict()
    write_json(root / "validation_report.json", rep)
    (root / "validation_report.md").write_text(_validation_md(rep), encoding="utf-8")
    tp = day_result.result
    with open(root / "portfolio.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "action", "current_shares", "target_shares", "target_weight", "est_weight_after"])
        est_w = getattr(tp, "est_weights", {}) or {}
        for p in getattr(tp, "plan", []) or []:
            w.writerow([p.ticker, p.action, p.current_shares, p.target_shares, f"{float(p.target_weight):.6f}",
                        f"{float(est_w.get(p.ticker, 0)):.6f}"])
    with open(root / "orders.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "side", "shares", "decision_ref"])
        for o in doc["orders"]:
            w.writerow([o["ticker"], o["side"], o["shares"], o["decision_ref"]])
    write_json(root / "facts.json", {"observations": doc["observations"], "inferences": doc["inferences"],
                                     "market_view": doc["market_view"]})
    raw_manifest = ROOT / "data" / "raw" / ymd(day_result.prev_date or trade_date) / "manifest.json"
    write_json(root / "sources_manifest.json", {
        "dplan_sources": doc["sources"],
        "raw_manifest_path": str(raw_manifest.relative_to(ROOT)) if raw_manifest.exists() else None,
        "raw_manifest_sha256": sha256_file(raw_manifest) if raw_manifest.exists() else None,
        "store_manifest_hash": (data_health or {}).get("store_manifest_hash")})
    write_json(root / "data_health.json", data_health or {"note": "refresh not run"})
    write_json(root / "reconciliation.json", reconciliation or {"status": "UNAVAILABLE"})
    write_json(root / "preflight.json", preflight or {})
    for name, obj in (extra_json or {}).items():
        write_json(root / name, obj)
    meta = dict(run_metadata, dplan_sha256=sha256_file(root / fname), mode=mode, run_id=run_id)
    write_json(root / "run_metadata.json", meta)
    (root / "README.txt").write_text(
        f"{BANNER}\nCANDIDATE PACKAGE  run_id={run_id}  mode={mode.upper()}\n{BANNER}\n"
        f"trade_date : {trade_date}\nteam_id    : {team_id}\nD-Plan     : {fname}\n"
        f"validation : {'PASS' if rep['ok'] else 'FAIL'}\n\n"
        "This folder is ONE candidate. Upload ONLY the file referenced by ../../FINAL_CANDIDATE.txt\n"
        "(submissions/YYYYMMDD/FINAL/...). Never upload from candidates/ directly.\n", encoding="utf-8")
    files = sorted(p for p in root.iterdir() if p.is_file())
    write_json(root / "manifest.json", {"run_id": run_id, "created_at": datetime.now(TPE).isoformat(),
                                        "files": [{"filename": p.name, "sha256": sha256_file(p), "size": p.stat().st_size,
                                                   "created_at": datetime.fromtimestamp(p.stat().st_mtime, TPE).isoformat()}
                                                  for p in files]})
    return root


def verify_package(pkg: Path) -> list[str]:
    """Re-hash every file against manifest.json. Returns problems (empty = intact)."""
    m = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    probs = []
    for f in m["files"]:
        p = pkg / f["filename"]
        if not p.exists():
            probs.append(f"missing {f['filename']}")
        elif sha256_file(p) != f["sha256"]:
            probs.append(f"hash mismatch {f['filename']}")
    return probs


def mark_final(pkg: Path, *, team_id: str, trade_date: str, mode: str, ops_cfg: dict | None = None) -> dict:
    """Promote a candidate to FINAL_CANDIDATE after strict checks. Returns {ok, reasons, ...}."""
    ops_cfg = ops_cfg or load_ops_config()
    reasons = []
    fname = f"D-Plan_{team_id}_{trade_date}.json"
    meta = json.loads((pkg / "run_metadata.json").read_text(encoding="utf-8"))
    rep = json.loads((pkg / "validation_report.json").read_text(encoding="utf-8"))
    dp = pkg / fname
    if not dp.exists():
        reasons.append(f"expected file {fname} not in package")
    else:
        doc = json.loads(dp.read_text(encoding="utf-8"))
        if doc.get("team_id") != team_id:
            reasons.append(f"team_id {doc.get('team_id')} != {team_id}")
        if doc.get("trade_date") != trade_date:
            reasons.append(f"trade_date {doc.get('trade_date')} != {trade_date}")
        if sha256_file(dp) != meta.get("dplan_sha256"):
            reasons.append("D-Plan hash changed after validation")
    if not rep.get("ok"):
        reasons.append("validation FAIL")
    reasons += verify_package(pkg)
    day = ops_path(ops_cfg, "submissions_dir") / ymd(trade_date)
    if reasons:
        return {"ok": False, "reasons": reasons}
    final_dir = day / "FINAL"
    final_dir.mkdir(parents=True, exist_ok=True)
    for old in final_dir.glob("*.json"):
        old.unlink()                                   # FINAL holds exactly one file; history keeps the trail
    dst = final_dir / fname
    shutil.copy2(dp, dst)
    sha = sha256_file(dst)
    if sha != meta["dplan_sha256"]:
        dst.unlink()
        return {"ok": False, "reasons": ["copy hash mismatch"]}
    rec = {"marked_at": datetime.now(TPE).isoformat(), "trade_date": trade_date, "team_id": team_id, "file": fname,
           "path": str(dst.relative_to(ROOT)) if dst.is_relative_to(ROOT) else str(dst), "sha256": sha,
           "validation": "PASS", "run_id": meta["run_id"], "git_sha": meta.get("git_sha"),
           "generated_at": meta.get("generated_at"), "mode": mode}
    warn = ("*** DRY-RUN — NOT A COMPETITION SUBMISSION — DO NOT UPLOAD ***\n" if mode != "competition" else "")
    (day / "FINAL_CANDIDATE.txt").write_text(
        f"{BANNER}\n{warn}FINAL_CANDIDATE   trade date {trade_date}   team {team_id}\n{BANNER}\n"
        f"{'UPLOAD THIS FILE' if mode == 'competition' else 'DRY-RUN FILE    '} : {rec['path']}\n"
        f"FILE NAME        : {fname}\n"
        f"SHA256           : {sha}\n"
        f"VALIDATION       : PASS\n"
        f"GENERATED AT     : {rec['generated_at']}\n"
        f"GIT SHA          : {rec['git_sha']}\n"
        f"RUN ID           : {rec['run_id']}\n"
        f"MODE             : {mode.upper()}\n{BANNER}\n"
        "Before uploading: confirm the date and team id above, and that the upload window is open.\n"
        "After uploading: save the platform receipt into this folder (receipt_*.png/pdf/txt).\n", encoding="utf-8")
    with open(day / "final_history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True, **rec}
