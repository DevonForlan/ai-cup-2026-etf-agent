"""Submission package + FINAL_CANDIDATE marking / freeze / replacement. NO upload (NC-1).

Layout (per trade date):
  submissions/YYYYMMDD/candidates/<run_id>/   full package of one run (built in .partial, then renamed; immutable)
  submissions/YYYYMMDD/FINAL/D-Plan_<team>_<date>.json   the ONLY file meant for manual upload
  submissions/YYYYMMDD/FINAL_CANDIDATE.txt      big banner: file, sha256, validation, team, date, git sha, cutoff
  submissions/YYYYMMDD/FINAL_FREEZE.json        freeze record of the current FINAL (sha, fingerprint, inputs, operator)
  submissions/YYYYMMDD/final_history.jsonl      every MARKED / REPLACED / REFUSED event (append-only, never deleted)

A candidate is marked FINAL only if: validation PASS, team_id == expected, trade_date == expected,
filename == D-Plan_<team>_<date>.json, every file matches manifest.json, and the copy's sha256 equals the
validated file's sha256. Once a FINAL exists it is FROZEN: a later run never replaces it silently; only
mark_final(..., replace=True, reason=..., operator=...) (CLI: agent/ops/final.py replace-final) can.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
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
                  run_metadata: dict, ops_cfg: dict | None = None, extra_json: dict | None = None,
                  crash_hook=None) -> Path:
    ops_cfg = ops_cfg or load_ops_config()
    final_root = ops_path(ops_cfg, "submissions_dir") / ymd(trade_date) / "candidates" / run_id
    if final_root.exists():
        raise FileExistsError(f"candidate {final_root} exists; packages are immutable (use a new run_id)")
    root = final_root.with_name(f".{run_id}.partial")       # crash-safe: only a complete package is renamed
    if root.exists():
        shutil.rmtree(root)
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
        "store_manifest_hash": run_metadata.get("data_snapshot_hash")})
    write_json(root / "data_health.json", data_health or {"note": "refresh not run"})
    write_json(root / "reconciliation.json", reconciliation or {"status": "UNAVAILABLE"})
    write_json(root / "preflight.json", preflight or {})
    for name, obj in (extra_json or {}).items():
        write_json(root / name, obj)
    if crash_hook:
        crash_hook("package_mid")
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
    os.replace(root, final_root)
    return final_root


def verify_package(pkg: Path) -> list[str]:
    """Re-hash every file against manifest.json. Returns problems (empty = intact)."""
    mp = pkg / "manifest.json"
    if not mp.exists():
        return ["manifest.json missing (incomplete package)"]
    m = json.loads(mp.read_text(encoding="utf-8"))
    probs = []
    for f in m["files"]:
        p = pkg / f["filename"]
        if not p.exists():
            probs.append(f"missing {f['filename']}")
        elif sha256_file(p) != f["sha256"]:
            probs.append(f"hash mismatch {f['filename']}")
    return probs


def history(trade_date: str, ops_cfg: dict | None = None) -> list[dict]:
    p = ops_path(ops_cfg or load_ops_config(), "submissions_dir") / ymd(trade_date) / "final_history.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


ACTIVE_EVENTS = ("MARKED", "REPLACED", "SUPERSEDED_NON_COMPETITION")


def active_final(trade_date: str, ops_cfg: dict | None = None) -> dict | None:
    act = [h for h in history(trade_date, ops_cfg) if h.get("event", "MARKED") in ACTIVE_EVENTS]
    return act[-1] if act else None


def _append_history(day: Path, rec: dict) -> None:
    day.mkdir(parents=True, exist_ok=True)
    with open(day / "final_history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def banner(rec: dict, mode: str, cutoff: str | None = None) -> str:
    comp = mode == "competition"
    big = f"#####  {rec['trade_date']}  #####  {rec['team_id']}  #####"
    lines = [BANNER, BANNER]
    if not comp:
        lines += ["***  DRY-RUN — NOT A COMPETITION SUBMISSION — DO NOT UPLOAD  ***"]
    lines += [big, f"FINAL_CANDIDATE   status {'READY' if comp else 'NOT FOR UPLOAD'}   mode {mode.upper()}",
              BANNER,
              f"{'UPLOAD THIS FILE' if comp else 'DRY-RUN FILE    '} : {rec['path']}",
              f"TRADE DATE       : {rec['trade_date']}",
              f"TEAM ID          : {rec['team_id']}",
              f"FILE NAME        : {rec['file']}",
              f"SHA256           : {rec['sha256']}",
              f"VALIDATION       : PASS",
              f"DECISION FP      : {rec.get('decision_fingerprint')}",
              f"GENERATED AT     : {rec['generated_at']}",
              f"GIT SHA          : {rec['git_sha']}",
              f"RUN ID           : {rec['run_id']}",
              f"MODE             : {mode.upper()}",
              f"CUT-OFF          : {cutoff or '-'}  (submission window closes; do not upload after)",
              f"FROZEN BY        : {rec.get('operator')}  at {rec.get('marked_at')}",
              BANNER,
              "Before uploading: confirm the DATE and TEAM above, and that the upload window is open.",
              "After uploading: record the receipt: python -m agent.submission.receipt --date ... --sha256 ...",
              "A generated file is NOT a submission: state stays READY_TO_SUBMIT until a receipt matches."]
    return "\n".join(lines) + "\n"


def mark_final(pkg: Path, *, team_id: str, trade_date: str, mode: str, ops_cfg: dict | None = None,
               operator: str = "agent", replace: bool = False, reason: str | None = None,
               cutoff: str | None = None) -> dict:
    """Promote a candidate to FINAL after strict checks. Returns {ok, reasons, ...}.
    If a FINAL already exists: refused with kept=True unless replace=True with an operator and a reason."""
    ops_cfg = ops_cfg or load_ops_config()
    reasons = []
    fname = f"D-Plan_{team_id}_{trade_date}.json"
    day = ops_path(ops_cfg, "submissions_dir") / ymd(trade_date)
    if not (pkg / "run_metadata.json").exists():
        return {"ok": False, "reasons": ["incomplete package (no run_metadata.json)"]}
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
    if reasons:
        return {"ok": False, "reasons": reasons}
    cur = active_final(trade_date, ops_cfg)
    cur_ok = cur is not None and (day / "FINAL" / cur["file"]).exists()
    if cur_ok and cur["team_id"] != team_id:              # never "keep" / replace another team's FINAL silently
        _append_history(day, {"event": "REFUSED_OTHER_TEAM", "at": datetime.now(TPE).isoformat(),
                              "run_id": meta["run_id"], "team_id": team_id, "existing_team_id": cur["team_id"]})
        return {"ok": False, "reasons": [f"a FINAL for team {cur['team_id']} already exists for {trade_date}; "
                                         f"refusing to mark/keep for {team_id} (wrong team id?)"]}
    # Round 07 mode precedence: a competition run supersedes a non-competition (dry-run / historical) FINAL;
    # a non-competition run never replaces a competition FINAL (not even with replace-final).
    supersede = cur_ok and mode == "competition" and cur.get("mode") != "competition"
    if cur_ok and mode != "competition" and cur.get("mode") == "competition":
        _append_history(day, {"event": "REFUSED_COMPETITION_FINAL", "at": datetime.now(TPE).isoformat(),
                              "run_id": meta["run_id"], "mode": mode, "existing_sha256": cur["sha256"]})
        return {"ok": False, "kept": True, "existing": cur,
                "reasons": [f"a COMPETITION FINAL exists ({cur['run_id']}); a {mode} run never replaces it"]}
    if cur_ok and not replace and not supersede:
        _append_history(day, {"event": "REFUSED_FROZEN", "at": datetime.now(TPE).isoformat(), "run_id": meta["run_id"],
                              "sha256": meta["dplan_sha256"], "existing_sha256": cur["sha256"]})
        return {"ok": False, "kept": True, "existing": cur,
                "reasons": [f"FINAL already frozen ({cur['run_id']}); use replace-final to change it"]}
    if replace and cur_ok and not supersede and (not (reason or "").strip() or not (operator or "").strip() or operator == "agent"):
        return {"ok": False, "reasons": ["replace-final requires a human operator name and a reason"]}
    final_dir = day / "FINAL"
    final_dir.mkdir(parents=True, exist_ok=True)
    dst = final_dir / fname
    tmp = final_dir / f".{fname}.tmp"
    shutil.copy2(dp, tmp)
    sha = sha256_file(tmp)
    if sha != meta["dplan_sha256"]:
        tmp.unlink()
        return {"ok": False, "reasons": ["copy hash mismatch"]}
    os.replace(tmp, dst)                                   # atomic: FINAL is never half-written
    for old in final_dir.glob("*.json"):
        if old.name != fname:
            old.unlink()                                   # FINAL holds exactly one file; history keeps the trail
    now = datetime.now(TPE).isoformat()
    rec = {"event": "SUPERSEDED_NON_COMPETITION" if supersede else ("REPLACED" if (replace and cur_ok) else "MARKED"), "marked_at": now, "trade_date": trade_date,
           "team_id": team_id, "file": fname,
           "path": str(dst.relative_to(ROOT)) if dst.is_relative_to(ROOT) else str(dst), "sha256": sha,
           "validation": "PASS", "run_id": meta["run_id"], "git_sha": meta.get("git_sha"),
           "generated_at": meta.get("generated_at"), "mode": mode, "operator": operator,
           "decision_fingerprint": meta.get("decision_fingerprint")}
    if rec["event"] == "REPLACED":
        rec.update(old_sha256=cur["sha256"], old_run_id=cur["run_id"], reason=reason)
    elif supersede:
        rec.update(old_sha256=cur["sha256"], old_run_id=cur["run_id"], old_mode=cur.get("mode"),
                   reason="competition run supersedes a non-competition FINAL")
    write_json(day / "FINAL_FREEZE.json", {
        "trade_date": trade_date, "team_id": team_id, "file": fname, "sha256": sha, "git_sha": meta.get("git_sha"),
        "decision_fingerprint": meta.get("decision_fingerprint"), "data_snapshot_hash": meta.get("data_snapshot_hash"),
        "settlement_hash": meta.get("settlement_hash"), "config_hashes": meta.get("config_hashes"),
        "generated_at": meta.get("generated_at"), "frozen_at": now, "operator": operator, "run_id": meta["run_id"],
        "mode": mode, "replaces": rec.get("old_sha256")})
    (day / "FINAL_CANDIDATE.txt").write_text(banner(rec, mode, cutoff), encoding="utf-8")
    _append_history(day, rec)
    return {"ok": True, **rec}
