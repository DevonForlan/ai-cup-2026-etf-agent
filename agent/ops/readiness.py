"""Automated readiness score (Round 06): DEV_READY / DRY_RUN_READY / COMPETITION_READY with reasons.

  python agent\\ops\\readiness.py [--run-tests]      -> reports/round06_readiness.json

DEV_READY          all tests pass, Quant v1 baseline reproduced
DRY_RUN_READY      + 24-day dress rehearsal PASS, soak PASS, security scan PASS, FINAL safety tests PASS
COMPETITION_READY  + NC-1 confirmed (official settlement path AND submission path), critical data sources
                   reliable, latest real preflight not BLOCK, no open blocker.
NC-1 unresolved -> at most DRY_RUN_READY (never reported as COMPETITION_READY).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.ops.common import write_json  # noqa: E402

BASELINE_NAV = Decimal("1014240575.839861741934859718")


def run_tests() -> dict:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-o", "addopts="], cwd=ROOT, capture_output=True,
                       text=True, timeout=1800)
    tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
    m = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|error|errors|skipped)", tail[0])}
    res = {"summary": tail[0], "passed": m.get("passed", 0), "failed": m.get("failed", 0) + m.get("error", 0)
           + m.get("errors", 0), "ok": r.returncode == 0}
    write_json(ROOT / "reports" / "round06_test_results.json", res)
    return res


def _latest(glob: str) -> Path | None:
    xs = sorted(ROOT.glob(glob), key=lambda p: p.stat().st_mtime)
    return xs[-1] if xs else None


def _json(p: Path | None):
    return json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else None


def assess(tests: dict | None = None) -> dict:
    from agent.rules.organizer_clarifications import load as load_clar
    items = []

    def add(name, ok, detail, level):
        items.append({"item": name, "ok": bool(ok), "detail": detail, "required_for": level})
    tests = tests or _json(ROOT / "reports" / "round06_test_results.json") or {}
    add("all tests pass", tests.get("ok") and tests.get("failed", 1) == 0, tests.get("summary", "not run"), "DEV_READY")
    b = _json(ROOT / "sim_runs" / "round06_baseline_quant_v1" / "summary.json") or {}
    add("Quant v1 W5 baseline reproduced", b and Decimal(b["final_nav"]) == BASELINE_NAV and b["warning_count"] == 0
        and b["validation_failures"] == 0 and b["fallback_days"] == 0, b.get("final_nav", "missing"), "DEV_READY")
    rh = [(_json(p), p) for p in ROOT.glob("rehearsal/*/rehearsal_summary.json")]
    full = [(s, p) for s, p in rh if s and s["days"] >= 24]
    good = [(s, p) for s, p in full if s["passed"]]
    add("24-day dress rehearsal PASS", bool(good),
        "; ".join(f"{s['mode']} {s['criteria']['operational_pass']} ({p.parent.name})" for s, p in full) or "none",
        "DRY_RUN_READY")
    add("24-day rehearsal in competition mode (clock-sim)", any(s["mode"] == "clock-sim" for s, _ in good),
        "clock-sim PASS" if any(s["mode"] == "clock-sim" for s, _ in good) else "missing", "DRY_RUN_READY")
    so = _json(ROOT / "reports" / "round06_soak_summary.json") or {}
    add("soak test PASS (>=50 iterations)", so.get("passed") and so.get("iterations", 0) >= 50,
        f"{so.get('iterations')} iterations, problems {so.get('iterations_with_problems')}, "
        f"unexpected {so.get('unexpected_exceptions')}", "DRY_RUN_READY")
    sec = _json(ROOT / "reports" / "round06_security_scan.json") or {}
    add("security scan PASS", sec.get("passed"), f"{len(sec.get('findings', []))} findings", "DRY_RUN_READY")
    fi = ROOT / "reports" / "round06_failure_injection.csv"
    fir = list(csv.DictReader(open(fi, encoding="utf-8-sig"))) if fi.exists() else []
    add("failure injection round 2 PASS", fir and all(r["result"] == "PASS" for r in fir),
        f"{sum(r['result'] == 'PASS' for r in fir)}/{len(fir)}" if fir else "not run", "DRY_RUN_READY")
    clar = load_clar()
    nc1 = clar["NC-1"]["status"]
    add("NC-1 official settlement path confirmed", nc1 == "confirmed", f"NC-1 {nc1}", "COMPETITION_READY")
    add("NC-1 official submission path confirmed", nc1 == "confirmed", f"NC-1 {nc1}; ManualSubmissionProvider only",
        "COMPETITION_READY")
    add("first trading day confirmed (NC-15)", clar["NC-15"]["status"] == "confirmed", clar["NC-15"]["status"],
        "COMPETITION_READY")
    srel = ROOT / "reports" / "source_reliability.csv"
    rel = {r["source"]: r for r in csv.DictReader(open(srel, encoding="utf-8-sig"))} if srel.exists() else {}
    crit_ok = all(rel.get(s) and int(rel[s]["attempts"]) >= 3 and int(rel[s]["failure"]) == 0
                  for s in ("twse_prices", "tpex_prices"))
    add("critical sources reliable (>=3 live attempts, 0 failures)", crit_ok,
        {s: (rel[s]["attempts"], rel[s]["failure"]) for s in ("twse_prices", "tpex_prices") if s in rel} or "no live data",
        "COMPETITION_READY")
    pf = _latest("logs/ops/*/preflight.json")
    pj = _json(pf) or {}
    add("latest real preflight not BLOCK", pj.get("level") in ("PASS", "WARN"),
        f"{pf.parent.name if pf else '-'}: {pj.get('level')}", "COMPETITION_READY")
    real_llm = any((ROOT / ".env").exists() for _ in [0])
    order = ["DEV_READY", "DRY_RUN_READY", "COMPETITION_READY"]
    level = "NOT_READY"
    for lv in order:
        if all(i["ok"] for i in items if order.index(i["required_for"]) <= order.index(lv)):
            level = lv
        else:
            break
    blockers = [i for i in items if not i["ok"]]
    res = {"level": level, "items": items, "blockers": [f"{i['item']}: {i['detail']}" for i in blockers],
           "nc1_status": nc1, "cap_reason": "NC-1 unresolved -> max DRY_RUN_READY" if nc1 != "confirmed" else None,
           "real_llm": "PRESENT(.env)" if real_llm else "BLOCKED_NO_API_KEY"}
    write_json(ROOT / "reports" / "round06_readiness.json", res)
    return res


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-tests", action="store_true")
    a = ap.parse_args(argv)
    t = run_tests() if a.run_tests else None
    r = assess(t)
    for i in r["items"]:
        print(f"[{'OK' if i['ok'] else '--'}] {i['required_for']:18s} {i['item']}: {i['detail']}")
    print("READINESS:", r["level"], f"({r['cap_reason']})" if r["cap_reason"] else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
