"""Verify a release candidate git SHA WITHOUT touching the working tree (Round 06).

  python agent\\ops\\verify_release.py --sha <sha> [--smoke]

Checks at <sha> (read via `git show`, never checkout/reset): commit exists; config/strategy_quant_v1.yaml sha256
== freeze record; official config/competition.yaml, D-Plan schema, universe and active-ETF list identical to
HEAD (official inputs must not drift); config hashes listed. --smoke: `git worktree add --detach` a temp checkout,
run a smoke test subset there with this venv, then remove the worktree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.ops.common import load_ops_config, write_json  # noqa: E402

OFFICIAL = ["config/competition.yaml", "D-Plan.schema_v4.2.json", "research/official_updates/D-Plan.schema_v4.3.json",
            "config/universe_150.csv"]
SMOKE = ["tests/engine", "tests/ops/test_ops_units.py", "tests/test_end_to_end.py"]


def _git(*a) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True)


def blob_sha(sha: str, path: str) -> str | None:
    r = _git("show", f"{sha}:{path}")
    return "sha256:" + hashlib.sha256(r.stdout).hexdigest() if r.returncode == 0 else None


def verify(sha: str, smoke: bool = False) -> dict:
    res = {"sha": sha, "checks": []}

    def add(name, ok, detail=""):
        res["checks"].append({"check": name, "ok": bool(ok), "detail": detail})
    full = _git("rev-parse", "--verify", f"{sha}^{{commit}}")
    add("commit exists", full.returncode == 0, full.stdout.decode().strip())
    if full.returncode != 0:
        res["passed"] = False
        return res
    fz = load_ops_config().get("freeze") or {}
    st = blob_sha(sha, fz.get("strategy_config", "config/strategy_quant_v1.yaml"))
    add("strategy config == freeze record", st == fz.get("strategy_sha256"), st or "missing")
    for p in OFFICIAL:
        a, b = blob_sha(sha, p), blob_sha("HEAD", p)
        add(f"official input unchanged: {p}", a is not None and a == b, (a or "missing")[:23])
    cfgs = _git("ls-tree", "--name-only", sha, "config/").stdout.decode().split()
    res["config_hashes"] = {c: blob_sha(sha, c) for c in cfgs if c.endswith(".yaml")}
    prompts = _git("ls-tree", "--name-only", sha, "agent/llm/prompts/").stdout.decode().split()
    res["prompt_hashes"] = {p: blob_sha(sha, p) for p in prompts}
    dirty = _git("status", "--porcelain", "--", "agent", "config").stdout.decode().strip()
    res["working_tree_dirty_paths"] = dirty.splitlines()[:10]
    if smoke:
        wt = Path(tempfile.mkdtemp(prefix="relverify_")) / "wt"
        r = _git("worktree", "add", "--detach", str(wt), sha)
        try:
            t = subprocess.run([sys.executable, "-m", "pytest", "-q", "-o", "addopts=", "-p", "no:cacheprovider", *SMOKE],
                               cwd=wt, capture_output=True, text=True, timeout=1200)
            tail = (t.stdout.strip().splitlines() or [""])[-1]
            add("smoke tests at sha (temp worktree)", r.returncode == 0 and t.returncode == 0, tail)
        finally:
            _git("worktree", "remove", "--force", str(wt))
            _git("worktree", "prune")
    res["passed"] = all(c["ok"] for c in res["checks"])
    write_json(ROOT / "reports" / "round06_verify_release.json", res)
    return res


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", default="HEAD")
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args(argv)
    r = verify(a.sha, a.smoke)
    for c in r["checks"]:
        print(f"[{'OK' if c['ok'] else 'FAIL'}] {c['check']}  {c['detail']}")
    print("RELEASE VERIFY:", "PASS" if r["passed"] else "FAIL")
    return 0 if r["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
