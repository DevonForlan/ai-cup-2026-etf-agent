"""Issue #43: publish TACTICAL_OVERRIDE_V1 records (entry / unwind, version, fingerprint, tickers, weights, quantities, status)
to the `shared-state` branch under shared_state/tactical/. Downstream only: every error is swallowed, nothing here can change
a decision, a D-Plan or a submission. The record states honestly whether the FINAL of that date is SUBMISSION_CONFIRMED.

    python -m agent.ops.shared_state_tactical [--root PRODUCTION_ROOT] [--no-push]
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.ops import shared_state_sync as S

REL = "shared_state/tactical"


def _records(root: Path) -> list[Path]:
    d = root / "logs" / "tactical"
    return sorted(d.glob("*.json")) if d.is_dir() else []


def _doc(path: Path, root: Path) -> dict:
    raw = path.read_bytes()
    rec = json.loads(raw.decode("utf-8"))
    td = rec["trade_date"]
    conf = S.confirmed_record(td, root)
    rec["source_record"] = path.relative_to(root).as_posix()
    rec["source_sha256"] = "sha256:" + S._sha(raw)
    rec["final_sha256"] = conf["sha256"] if conf else None
    rec["final_path"] = f"shared_state/daily_submissions/{td}/FINAL.json" if conf else None
    rec["submission_status"] = conf["status"] if conf else "NOT_CONFIRMED"
    rec["submitted_at"] = conf["submitted_at"] if conf else None
    rec["confirmed_at"] = conf["confirmed_at"] if conf else None
    return rec


def publish(root=None, *, push: bool = True) -> list[dict]:
    """Publish every tactical record that changed. Never raises."""
    out = []
    try:
        root = S._root(root)
        recs = _records(root)
        if not recs:
            return out
        wt = S.ensure_worktree(root)
        base = wt / REL
        base.mkdir(parents=True, exist_ok=True)
        ga = wt / ".gitattributes"                  # same rule as the other snapshots: git never rewrites line endings
        if not ga.exists() or "shared_state/** -text" not in ga.read_text(encoding="utf-8"):
            ga.write_text((ga.read_text(encoding="utf-8") if ga.exists() else "") + "shared_state/** -text" + chr(10),
                          encoding="utf-8", newline=chr(10))
        latest = None
        changed = []
        for p in recs:
            doc = _doc(p, root)
            name = f"{doc['trade_date']}_{doc.get('phase', 'NA')}.json"
            doc["idempotency_key"] = f"{name}|{doc['source_sha256']}|{doc['submission_status']}|{doc['final_sha256']}"
            target = base / name
            prev = None
            try:
                prev = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            if prev and prev.get("idempotency_key") == doc["idempotency_key"]:
                out.append({"record": name, "status": "ALREADY_SYNCED"})
            else:
                doc["synced_at"] = S._now()
                target.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + chr(10), encoding="utf-8", newline=chr(10))
                changed.append(name)
                out.append({"record": name, "status": "SYNCED"})
            if latest is None or (doc["trade_date"], doc.get("phase", "")) >= (latest["trade_date"], latest.get("phase", "")):
                latest = {k: doc.get(k) for k in ("trade_date", "phase", "status", "tactical_status", "version", "fingerprint",
                                                  "x_effective", "submission_status", "final_sha256")}
                latest["record_path"] = f"{REL}/{name}"
        if latest:
            lp = base / "latest.json"
            new = json.dumps(latest, ensure_ascii=False, indent=1) + chr(10)
            if not lp.exists() or lp.read_text(encoding="utf-8") != new:
                lp.write_text(new, encoding="utf-8", newline=chr(10))
                changed.append("latest.json")
        if changed:
            S._git(wt, "add", "-A", REL, ".gitattributes")
            if S._git(wt, "diff", "--cached", "--quiet", check=False).returncode != 0:
                S._git(wt, "commit", "-q", "-m", "shared-state: tactical override " + ", ".join(changed)[:120]
                       + "\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>")
        if push and (changed or "ahead" in S._git(wt, "status", "-sb", check=False).stdout.splitlines()[0]):
            last = ""
            for _ in range(S.PUSH_ATTEMPTS):
                r = S._git(wt, "push", "-u", "origin", S.BRANCH, check=False)
                if r.returncode == 0:
                    break
                last = (r.stderr or r.stdout).strip()[:300]
                S._git(wt, "pull", "--rebase", "origin", S.BRANCH, check=False)
            else:
                raise RuntimeError(f"push failed: {last}")
    except Exception as e:  # noqa: BLE001  downstream only
        out.append({"record": None, "status": "SYNC_PENDING", "detail": str(e)[:300]})
    return out


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Publish tactical-override records to the shared-state branch (Issue #43)")
    ap.add_argument("--root", default=None)
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args(argv)
    res = publish(a.root, push=not a.no_push)
    for r in res:
        print(json.dumps(r, ensure_ascii=False))
    return 0 if all(r["status"] != "SYNC_PENDING" for r in res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
