"""Failure injection round 2 (Round 06) on the synthetic fixture store, each case in its own temp root.

  python agent\\ops\\failure_injection_r2.py      -> reports/round06_failure_injection.csv
"""
from __future__ import annotations

import copy
import csv
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.ops.common import Clock, load_ops_config, sha256_file  # noqa: E402

T1, CLK = "2026-10-26", "2026-10-25T20:00:00+08:00"
GIT = {"sha": "fi2", "branch": "master", "dirty_paths": []}


def _cfg(root: Path) -> dict:
    c = copy.deepcopy(load_ops_config())
    for i, k in enumerate(c["paths"]):
        c["paths"][k] = str(root / f"{k[:3]}{i}")
    return c


def _fake(fail=(), latest="2026-10-23"):
    names = ["twse_prices", "tpex_prices", "twse_institutional", "tpex_institutional", "etf_holdings",
             "corporate_actions", "mops_revenue_first_seen", "mops_material_info", "taifex_night", "us_market"]

    def mk(n):
        def f(ctx):
            if n in fail:
                raise ConnectionError(f"injected: {n} unreachable")
            return {"records": 1, "latest_available_date": latest}
        return f
    return {n: mk(n) for n in names}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from agent.competition_day import SimulatedCrash, run_competition_day
    from agent.data.loaders import HistoryStore, load_fixture_store
    from agent.ops.archive_run import partial_dirs
    from agent.ops.package_submission import active_final, mark_final
    from agent.ops.refresh_daily import offline_fetchers
    from agent.ops.settlement_entry import import_settlement
    base = Path(tempfile.mkdtemp(prefix="fi2_"))
    store = load_fixture_store(ROOT / "tests" / "fixtures" / "synthetic", base / "store")
    trunc = base / "store_trunc"
    trunc.mkdir()
    for p in store.root.glob("*.parquet"):
        (trunc / p.name).write_bytes(p.read_bytes())
    ts = HistoryStore(trunc)
    for t in ("daily_prices", "institutional"):
        df = ts.load(t)
        df[df["date"] < "2026-10-23"].to_parquet(ts.path(t), index=False)
    ts = HistoryStore(trunc)
    rows = []

    def run(cfg, st=store, clock=CLK, **kw):
        kw.setdefault("skip_refresh", "refresh_fetchers" not in kw)
        return run_competition_day(T1, "TEAM_FI", kw.pop("mode", "competition"), store=st, store_is_fixture=True,
                                   ops_cfg=cfg, clock=Clock(clock), git=kw.pop("git", GIT), archive_readonly=False,
                                   initial=True, write_report=False, **kw)

    def case(name, injected, expected, fn):
        root = base / name
        root.mkdir()
        cfg = _cfg(root)
        t = time.perf_counter()
        try:
            actual, detail = fn(cfg, root)
        except Exception as e:  # noqa: BLE001
            actual, detail = "EXCEPTION", f"{type(e).__name__}: {e} {traceback.format_exc()[-300:]}"
        rows.append({"case": name, "injected": injected, "expected": expected, "actual": actual,
                     "result": "PASS" if actual == expected else "FAIL", "detail": str(detail)[:300],
                     "sec": round(time.perf_counter() - t, 1)})
        print(f"{name:26s} expected={expected:26s} actual={actual:26s} {rows[-1]['result']}", flush=True)

    def crash_then_recover(phase):
        def fn(cfg, root):
            def hook(n):
                if n == phase:
                    raise SimulatedCrash(n)
            try:
                run(cfg, crash_hook=hook)
            except SimulatedCrash:
                pass
            before = active_final(T1, cfg)
            s = run(cfg, clock="2026-10-25T20:05:00+08:00")
            fin = active_final(T1, cfg)
            ff = Path(cfg["paths"]["submissions_dir"]) / "20261026" / "FINAL" / fin["file"]
            ok = s["status"] == "READY_TO_SUBMIT" and sha256_file(ff) == fin["sha256"] and \
                (before is None or before["sha256"] == fin["sha256"]) and \
                all(p.name.endswith(".partial") for p in partial_dirs(cfg))
            return ("RECOVERED" if ok else "NOT_RECOVERED"), f"run_id {s.get('run_id')} final {fin['run_id']}"
        return fn

    def crash_refresh(cfg, root):
        f = _fake()

        def boom(ctx):
            raise SimulatedCrash("killed")
        f["mops_material_info"] = boom
        try:
            run(cfg, refresh_fetchers=f)
        except SimulatedCrash:
            pass
        s = run(cfg, clock="2026-10-25T20:05:00+08:00", refresh_fetchers=_fake())
        return ("RECOVERED" if s["status"] == "READY_TO_SUBMIT" else s["status"]), s.get("reason")

    def stale_lock(cfg, root):
        from agent.data.locks import FileLock
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        lock = root / "manifest.lock"
        lock.write_text(json.dumps({"pid": p.pid, "host": socket.gethostname()}), encoding="utf-8")
        old = time.time() - 900
        os.utime(lock, (old, old))
        with FileLock(lock, timeout=5, stale_after=120, audit_log=root / "lock_audit.jsonl"):
            pass
        ok = not lock.exists() and (root / "lock_audit.jsonl").exists() and list(root.glob("manifest.lock.stale-*"))
        return ("RECOVERED_AUDITED" if ok else "NOT_RECOVERED"), ""

    def entry(rows_csv):
        def fn(cfg, root):
            f = root / "a.csv"
            f.write_text("\n".join(rows_csv) + "\n", encoding="utf-8")
            r = import_settlement("2026-10-26", f, operator="op", source="src", ops_cfg=cfg,
                                  closes={"2330": 1000.0, "2317": 100.0})
            written = (Path(cfg["paths"]["settlement_dir"]) / "20261026_official.json").exists()
            return (r["status"] if not written or r["status"] != "BLOCK" else "BLOCK_BUT_WRITTEN"), r["problems"][:2]
        return fn
    good_tail = ["__DATE__,2026-10-26", "__CASH__,1000000", "__NAV__,23000000", "__ACCRUED__,0", "__WARNINGS__,"]

    def wrong(field):
        def fn(cfg, root):
            s = run(cfg)
            pkg = Path(s["package"])
            if field == "team":
                r = mark_final(pkg, team_id="TEAM_OTHER", trade_date=T1, mode="competition", ops_cfg=cfg)
            elif field == "date":
                r = mark_final(pkg, team_id="TEAM_FI", trade_date="2026-10-27", mode="competition", ops_cfg=cfg)
            else:                                            # hash: FINAL file edited after freeze
                from agent.submission.manual import ManualSubmissionProvider
                fin = active_final(T1, cfg)
                ff = Path(cfg["paths"]["submissions_dir"]) / "20261026" / "FINAL" / fin["file"]
                ff.write_text(ff.read_text(encoding="utf-8").replace('"orders"', '"orders" ', 1), encoding="utf-8")
                p = ManualSubmissionProvider(cfg).prepare(T1, "TEAM_FI")
                return ("REFUSED" if not p["ok"] and "hash changed" in " ".join(p["problems"]) else "ACCEPTED"), p["problems"]
            return ("REFUSED" if not r["ok"] else "ACCEPTED"), r.get("reasons")
        return fn

    def replacement(cfg, root):
        from agent.ops.final import replace_final
        run(cfg)
        b = run(cfg, clock="2026-10-25T20:10:00+08:00")
        silent = b["final_action"] == "KEPT_IDENTICAL"
        no_reason = mark_final(Path(b["package"]), team_id="TEAM_FI", trade_date=T1, mode="competition", ops_cfg=cfg,
                               replace=True, operator="op")["ok"]
        r = replace_final(T1, "TEAM_FI", b["run_id"], reason="test", operator="op", ops_cfg=cfg,
                          clock=Clock("2026-10-25T20:20:00+08:00"))
        return ("EXPLICIT_ONLY" if silent and not no_reason and r["ok"] else "UNSAFE"), r.get("event")

    def offline(cfg, root):
        s = run(cfg, mode="dry-run", refresh_fetchers=offline_fetchers())
        return (f"{s['status']}/L{s.get('degradation_level')}"), s.get("data_health")

    def offline_missing(cfg, root):
        s = run(cfg, st=ts, refresh_fetchers=offline_fetchers())
        return s["status"], (s.get("reason") or "")[:120]

    def skew(cfg, root):
        ref = Clock(CLK).now() + timedelta(minutes=15)
        s = run(cfg, reference_time=ref)
        return s["status"], (s.get("reason") or "")[:120]

    case("crash_during_refresh", "process killed inside refresh", "RECOVERED", crash_refresh)
    case("crash_before_package", "process killed after validation", "RECOVERED", crash_then_recover("before_package"))
    case("crash_mid_package", "process killed while writing package", "RECOVERED", crash_then_recover("package_mid"))
    case("archive_partial_failure", "process killed while archiving", "RECOVERED", crash_then_recover("archive_mid"))
    case("stale_lock", "lock file of a dead process (15 min old)", "RECOVERED_AUDITED", stale_lock)
    case("invalid_settlement_csv", "garbage CSV", "BLOCK", entry(["ticker,shares", "2330", "abc,def", "__CASH__,x"]))
    case("duplicate_settlement_ticker", "2330 twice", "BLOCK", entry(["ticker,shares", "2330,17000", "2330,1000"] + good_tail))
    case("wrong_nav", "NAV != sum(shares x close) + cash", "BLOCK",
         entry(["ticker,shares", "2330,17000", "2317,50000", "__DATE__,2026-10-26", "__CASH__,1000000",
                "__NAV__,30000000", "__ACCRUED__,0", "__WARNINGS__,"]))
    case("wrong_team", "mark FINAL with another team id", "REFUSED", wrong("team"))
    case("wrong_date", "mark FINAL for another date", "REFUSED", wrong("date"))
    case("hash_mismatch", "FINAL file edited after freeze", "REFUSED", wrong("hash"))
    case("final_replacement", "second run + replace without/with reason", "EXPLICIT_ONLY", replacement)
    case("no_internet_t1_cached", "all sources unreachable, T-1 already stored", "DRY_RUN_OK/L2", offline)
    case("critical_source_missing", "unreachable and T-1 prices not stored", "BLOCKED", offline_missing)
    case("optional_source_missing", "US / TAIFEX / MOPS unreachable", "READY_TO_SUBMIT",
         lambda cfg, root: (run(cfg, refresh_fetchers=_fake(fail={"us_market", "taifex_night", "mops_material_info",
                                                                   "mops_revenue_first_seen"}))["status"], ""))
    case("past_cutoff", "run at 08:58", "LATE_PAST_CUTOFF",
         lambda cfg, root: (run(cfg, clock="2026-10-26T08:58:00+08:00")["status"], ""))
    case("clock_skew", "system clock 15 min off vs reference (competition)", "BLOCKED", skew)
    out = ROOT / "reports" / "round06_failure_injection.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{sum(r['result'] == 'PASS' for r in rows)}/{len(rows)} PASS -> {out}")
    return 0 if all(r["result"] == "PASS" for r in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
