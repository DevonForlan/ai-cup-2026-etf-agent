"""Issue #31 — publish every SUBMISSION_CONFIRMED FINAL to GitHub Shared State (read-only observability).

    branch `shared-state` (dedicated worktree <root>/.worktrees/shared-state; the production checkout is never touched)
      shared_state/daily_submissions/latest.json            pointer to the newest confirmed FINAL
      shared_state/daily_submissions/<date>/FINAL.json      byte-exact copy of the submitted D-Plan
      shared_state/daily_submissions/<date>/manifest.json   integrity + status evidence (idempotency key)
      shared_state/daily_submissions/<date>/summary.md      concise human summary (only fields present in the sources)
      shared_state/daily_submissions/<date>/superseded/<sha8>/{FINAL.json,manifest.json}   audit trail

Downstream only: a failure here never changes a submission, never retries or replaces it and never raises. A failed push
leaves `logs/shared_state/pending.json`; every later `sweep` retries it (bounded per run). Only the FINAL and
whitelisted metadata are copied - no receipts, screenshots, cookies, tokens or browser data.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from agent.ops.common import TPE

BRANCH = "shared-state"
REL = "shared_state/daily_submissions"
DONE = ("SUBMISSION_CONFIRMED", "ACCEPTED")
GIT_TIMEOUT = 90
PUSH_ATTEMPTS = 3


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _norm(s: str | None) -> str:
    return (s or "").replace("sha256:", "").lower()


def _now() -> str:
    return datetime.now(TPE).replace(microsecond=0).isoformat()


def _root(root) -> Path:
    if root is None:
        from agent.config import ROOT
        root = ROOT
    return Path(root)


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=GIT_TIMEOUT)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def confirmed_record(trade_date: str, root=None, team: str | None = None) -> dict | None:
    """The date's confirmed FINAL (None unless the status file says SUBMISSION_CONFIRMED and the FINAL on disk matches)."""
    root = _root(root)
    day = root / "submissions" / trade_date.replace("-", "")
    try:
        st = json.loads((day / "submission_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if st.get("state") not in DONE or st.get("trade_date") != trade_date:
        return None
    team_id = st.get("team_id")
    if team is None:
        from agent.ops.common import load_ops_config
        team = load_ops_config()["team"]["competition_team_id"]
    if not team_id or team_id != team:
        return None                      # TEAM_TEST / rehearsal plans are never published
    f = day / "FINAL" / f"D-Plan_{team_id}_{trade_date}.json"
    if not f.is_file():
        return None
    data = f.read_bytes()
    sha = _sha(data)
    if _norm(st.get("dplan_sha256")) != sha:
        return None                      # state and file disagree: never publish something that is not the confirmed FINAL
    confirmed_at = next((h.get("at") for h in reversed(st.get("history") or []) if h.get("to") in DONE), None)
    submitted_at = next((h.get("at") for h in st.get("history") or [] if h.get("to") == "SUBMITTED_UNVERIFIED"), None)
    return {"trade_date": trade_date, "team_id": team_id, "file": f, "data": data, "sha256": sha,
            "status": st["state"], "submitted_at": submitted_at or confirmed_at, "confirmed_at": confirmed_at,
            "source_path": f.relative_to(root).as_posix()}


def _opening_ledger(root: Path, trade_date: str) -> dict | None:
    """Start-of-day account from the latest internal settlement before trade_date (labelled as such; optional)."""
    cands = sorted(p for p in (root / "data" / "settlement").glob("*_internal.json")
                   if len(p.stem.split("_")[0]) == 8 and p.stem.split("_")[0].isdigit())
    best = None
    for p in cands:
        d = f"{p.stem[:4]}-{p.stem[4:6]}-{p.stem[6:8]}"
        if d < trade_date:
            best = (d, p)
    if not best:
        return None
    try:
        j = json.loads(best[1].read_text(encoding="utf-8"))
        nav, cash = float(j["nav"]), float(j["cash"])
        return {"as_of": best[0], "holdings": len(j["holdings"]), "cash_ratio": round(cash / nav, 6) if nav else None,
                "nav": j["nav"]}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _summary_md(rec: dict, plan: dict, manifest: dict, opening: dict | None, supersedes: list[str]) -> str:
    mv = plan.get("market_view") if isinstance(plan.get("market_view"), dict) else {}
    meta = plan.get("agent_metadata") if isinstance(plan.get("agent_metadata"), dict) else {}
    na = "not available"
    rows = [
        ("Trade date", rec["trade_date"]), ("Team", rec["team_id"]), ("FINAL SHA256", f"`{rec['sha256']}`"),
        ("Official submission status", rec["status"]), ("Submitted at", rec["submitted_at"] or na),
        ("Confirmed at", rec["confirmed_at"] or na),
        ("Orders", len(plan.get("orders") or [])), ("No-trade decisions", len(plan.get("no_trade_decisions") or [])),
        ("Market regime", mv.get("regime", na)), ("Stance", mv.get("stance", na)),
        ("Code version", meta.get("code_version", na)), ("Source FINAL path (local)", f"`{rec['source_path']}`"),
    ]
    if opening:
        rows[8:8] = [(f"Holdings (start of day, settlement {opening['as_of']})", opening["holdings"]),
                     (f"Cash ratio (start of day, settlement {opening['as_of']})", opening["cash_ratio"])]
    else:
        rows[8:8] = [("Holdings / cash ratio", na)]
    rows.append(("Active Share", na + " in the published sources (see the 17:00 evaluation)"))
    if supersedes:
        rows.append(("Supersedes (audit copies kept)", ", ".join(f"`{s}`" for s in supersedes)))
    out = [f"# Submitted FINAL — {rec['trade_date']} ({rec['team_id']})", "",
           "`FINAL.json` in this folder is the **exact, byte-for-byte snapshot of the submitted plan** "
           "(its SHA256 equals the value below and `manifest.json`). Nothing was rewritten or regenerated.", "",
           "| Item | Value |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in rows]
    out += ["", f"Synced at {manifest['synced_at']}. Not an official settlement; NAV / close estimates are computed "
            "separately from this file and the day's closing prices. AI generated; human review required.", ""]
    return "\n".join(out)


def ensure_worktree(root: Path) -> Path:
    wt = root / ".worktrees" / "shared-state"
    if (wt / ".git").exists():
        return wt
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(root, "fetch", "origin", BRANCH, check=False)
    if _git(root, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{BRANCH}", check=False).returncode == 0:
        _git(root, "worktree", "add", "-B", BRANCH, str(wt), f"origin/{BRANCH}")
    else:
        _git(root, "worktree", "add", "--orphan", "-b", BRANCH, str(wt))
    return wt


def _pending_path(root: Path) -> Path:
    return root / "logs" / "shared_state" / "pending.json"


def _set_pending(root: Path, dates: dict) -> None:
    p = _pending_path(root)
    if not dates:
        p.unlink(missing_ok=True)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"updated_at": _now(), "pending": dates}, ensure_ascii=False, indent=1), encoding="utf-8")


def _load_pending(root: Path) -> dict:
    try:
        return json.loads(_pending_path(root).read_text(encoding="utf-8")).get("pending", {})
    except (OSError, ValueError):
        return {}


def _write_snapshot(wt: Path, rec: dict, root: Path) -> tuple[str, list[Path]]:
    """Write/refresh the date folder + latest pointer in the worktree. Returns (action, changed paths)."""
    base = wt / REL
    ga = wt / ".gitattributes"                         # git must never rewrite line endings: the snapshot is byte-exact
    if not ga.is_file():
        ga.write_text("shared_state/** -text" + chr(10), encoding="utf-8", newline=chr(10))
    day = base / rec["trade_date"]
    mp = day / "manifest.json"
    prev = None
    if mp.is_file():
        try:
            prev = json.loads(mp.read_text(encoding="utf-8"))
        except ValueError:
            prev = None
    if prev and _norm(prev.get("final_sha256")) == rec["sha256"] and (day / "FINAL.json").is_file():
        return "UNCHANGED", []
    chain = list(prev.get("supersedes", [])) if prev else []
    if prev and (day / "FINAL.json").is_file():          # a different confirmed FINAL replaces the date's: keep the old one
        old = _norm(prev["final_sha256"])
        arch = day / "superseded" / old[:8]
        arch.mkdir(parents=True, exist_ok=True)
        (arch / "FINAL.json").write_bytes((day / "FINAL.json").read_bytes())
        (arch / "manifest.json").write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
        chain.append(old)
    day.mkdir(parents=True, exist_ok=True)
    (day / "FINAL.json").write_bytes(rec["data"])
    if _sha((day / "FINAL.json").read_bytes()) != rec["sha256"]:
        raise RuntimeError("snapshot SHA256 differs from the source FINAL")
    synced = _now()
    manifest = {"trade_date": rec["trade_date"], "team_id": rec["team_id"],
                "final_path": f"{REL}/{rec['trade_date']}/FINAL.json", "final_sha256": rec["sha256"],
                "source_final_path": rec["source_path"], "submission_status": rec["status"],
                "submitted_at": rec["submitted_at"], "confirmed_at": rec["confirmed_at"], "synced_at": synced,
                "idempotency_key": f"{rec['trade_date']}|{rec['team_id']}|{rec['sha256']}", "supersedes": chain}
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (day / "summary.md").write_text(
        _summary_md(rec, json.loads(rec["data"].decode("utf-8")), manifest, _opening_ledger(root, rec["trade_date"]), chain),
        encoding="utf-8", newline="\n")
    latest = {k: manifest[k] for k in ("trade_date", "team_id", "final_path", "final_sha256", "submission_status",
                                       "submitted_at", "confirmed_at", "synced_at")}
    lp = base / "latest.json"
    try:
        cur = json.loads(lp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cur = None
    if not cur or cur.get("trade_date", "") <= rec["trade_date"]:       # a backfill of an older date never moves the pointer
        latest["summary_path"] = f"{REL}/{rec['trade_date']}/summary.md"
        lp.write_text(json.dumps(latest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return ("SUPERSEDED" if prev else "CREATED"), [base]


def sync(trade_date: str, root=None, *, push: bool = True) -> dict:
    """Publish one confirmed date. Never raises; the returned status is informational only."""
    root = _root(root)
    out = {"trade_date": trade_date, "status": "SKIPPED", "detail": ""}
    try:
        rec = confirmed_record(trade_date, root)
        if rec is None:
            out["detail"] = "not SUBMISSION_CONFIRMED (or FINAL does not match the status file)"
            return out
        out["final_sha256"] = rec["sha256"]
        wt = ensure_worktree(root)
        action, changed = _write_snapshot(wt, rec, root)
        out["action"] = action
        if action != "UNCHANGED":
            _git(wt, "add", "-A", REL, ".gitattributes")
            msg = (f"shared-state: {trade_date} {rec['team_id']} FINAL sha256:{rec['sha256'][:12]} "
                   f"{rec['status']}\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>")
            if _git(wt, "diff", "--cached", "--quiet", check=False).returncode != 0:
                _git(wt, "commit", "-q", "-m", msg)
        if push:
            ahead = _git(wt, "status", "-sb", check=False).stdout.splitlines()[0]
            if action != "UNCHANGED" or "ahead" in ahead or _load_pending(root).get(trade_date):
                last = ""
                for _ in range(PUSH_ATTEMPTS):
                    r = _git(wt, "push", "-u", "origin", BRANCH, check=False)
                    if r.returncode == 0:
                        break
                    last = (r.stderr or r.stdout).strip()[:300]
                    _git(wt, "pull", "--rebase", "origin", BRANCH, check=False)
                else:
                    raise RuntimeError(f"push failed: {last}")
        pend = _load_pending(root)
        out["status"] = "SYNCED" if (action != "UNCHANGED" or trade_date in pend) else "ALREADY_SYNCED"
        pend.pop(trade_date, None)
        _set_pending(root, pend)
    except Exception as e:  # noqa: BLE001  downstream only: record, never raise, never touch the submission
        out.update(status="SYNC_PENDING", detail=str(e)[:300])
        pend = _load_pending(root)
        pend[trade_date] = {"since": pend.get(trade_date, {}).get("since", _now()), "last_error": str(e)[:300],
                            "last_try": _now()}
        try:
            _set_pending(root, pend)
        except OSError:
            pass
    return out


def sweep(root=None, *, push: bool = True) -> list[dict]:
    """Sync every confirmed competition date not yet published, plus any pending retry. Safe to call after every run."""
    root = _root(root)
    res = []
    try:
        dates = sorted(p.name for p in (root / "submissions").iterdir() if len(p.name) == 8 and p.name.isdigit())
    except OSError:
        return res
    for d in dates:
        td = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        if td < "2026-10-27":                       # competition start: the earlier folders are rehearsal / TEST plans
            continue
        if confirmed_record(td, root) is not None:
            r = sync(td, root, push=push)
            if r["status"] != "SKIPPED":
                res.append(r)
    try:                                           # Issue #43: tactical-override records ride along (downstream only)
        from agent.ops import shared_state_tactical as _T
        _T.publish(root, push=push)
    except Exception:  # noqa: BLE001
        pass
    return res


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Publish SUBMISSION_CONFIRMED FINALs to the shared-state branch (Issue #31)")
    ap.add_argument("--root", default=None, help="production project root (default: this checkout)")
    ap.add_argument("--date", default=None, help="one trade date; default: sweep every confirmed competition date")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args(argv)
    res = [sync(a.date, a.root, push=not a.no_push)] if a.date else sweep(a.root, push=not a.no_push)
    for r in res:
        print(json.dumps(r, ensure_ascii=False))
    return 0 if all(r["status"] != "SYNC_PENDING" for r in res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
