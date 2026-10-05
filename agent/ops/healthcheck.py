"""Daily health dashboard -> HEALTHY / DEGRADED / BLOCKED (reads the artifacts of one trade date; no fetching).

  python agent\\ops\\healthcheck.py --date 2026-10-27 [--mode competition]

Components: data, settlement, strategy, dplan, llm, disk, clock, git.
  HEALTHY  every component PASS
  DEGRADED some WARN (e.g. optional data stale, template narrative, dry-run marker) - still submittable
  BLOCKED  any BLOCK (critical data missing, reconciliation BLOCK, no valid FINAL_CANDIDATE, frozen config changed)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.ops.common import (BLOCK, PASS, WARN, Check, Clock, load_ops_config, ops_path,  # noqa: E402
                              sha256_file, worst, write_json, ymd)

LABEL = {PASS: "HEALTHY", WARN: "DEGRADED", BLOCK: "BLOCKED"}


def _read(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def healthcheck(trade_date: str, *, mode: str = "dry-run", ops_cfg: dict | None = None, clock: Clock | None = None,
                git: dict | None = None) -> dict:
    ops_cfg = ops_cfg or load_ops_config()
    clock = clock or Clock()
    comp = mode == "competition"
    logs = ops_path(ops_cfg, "ops_logs_dir") / ymd(trade_date)
    sub = ops_path(ops_cfg, "submissions_dir") / ymd(trade_date)
    comps: dict[str, Check] = {}
    # data
    dh = _read(logs / "data_health.json")
    if dh is None:
        comps["data"] = Check("data", WARN, "no data_health.json (refresh not run)")
    else:
        comps["data"] = Check("data", dh["level"], ", ".join(f"{s['source']}={s['status']}" for s in dh["sources"]
                                                            if s["status"] != "OK") or "all sources OK")
    # settlement / reconciliation (summary of the run, if any)
    summ = _read(logs / "competition_day_summary.json")
    st = (summ or {}).get("settlement") or {}
    rec = st.get("reconciliation")
    if st.get("initial_day"):
        comps["settlement"] = Check("settlement", PASS, "initial day")
    elif rec == "MATCH":
        comps["settlement"] = Check("settlement", PASS, "reconciled MATCH")
    elif rec == "MINOR_DIFFERENCE":
        comps["settlement"] = Check("settlement", WARN, "MINOR_DIFFERENCE (see reconciliation.json)")
    elif rec == "BLOCK":
        comps["settlement"] = Check("settlement", BLOCK, "reconciliation BLOCK: human must confirm the official ledger")
    else:
        comps["settlement"] = Check("settlement", BLOCK if comp else WARN, f"reconciliation {rec or 'not run'}")
    # strategy freeze
    fz = ops_cfg.get("freeze") or {}
    if fz:
        h = sha256_file(ROOT / fz["strategy_config"])
        comps["strategy"] = Check("strategy", PASS if h == fz["strategy_sha256"] else BLOCK,
                                  f"{fz['strategy_config']} {'== freeze ' + fz['frozen_in_commit'] if h == fz['strategy_sha256'] else 'CHANGED since freeze'}")
    # D-Plan / FINAL_CANDIDATE
    from agent.ops.package_submission import active_final
    last = active_final(trade_date, ops_cfg)
    if last is None:
        comps["dplan"] = Check("dplan", BLOCK, "no FINAL_CANDIDATE for this trade date")
    else:
        f = ROOT / last["path"] if not Path(last["path"]).is_absolute() else Path(last["path"])
        ok = f.exists() and sha256_file(f) == last["sha256"]
        if not ok:
            lvl = BLOCK
        elif last["mode"] == "competition":
            lvl = PASS
        else:                                   # a dry-run FINAL is never a competition submission
            lvl = BLOCK if comp else WARN
        comps["dplan"] = Check("dplan", lvl, f"{last['file']} {last['sha256'][:19]} mode={last['mode']}"
                               + ("" if ok else " FILE MISSING / HASH MISMATCH"))
    # LLM
    llm = (summ or {}).get("llm") or {}
    comps["llm"] = Check("llm", PASS if llm.get("used") or llm.get("mode") == "template" else WARN,
                         json.dumps(llm, ensure_ascii=False)[:200] if llm else "no run summary")
    # disk
    free_gb = shutil.disk_usage(ROOT).free / 2**30
    comps["disk"] = Check("disk", PASS if free_gb >= ops_cfg["preflight"]["min_free_disk_gb"] else BLOCK,
                          f"{free_gb:.1f} GB free")
    # clock / deadline
    from agent.ops.deadline import status as dl_status
    d = dl_status(trade_date, clock, ops_cfg)
    comps["clock"] = Check("clock", {"NORMAL": PASS, "RESTRICTED": WARN, "NO_LLM": WARN, "PACKAGE_ONLY": WARN,
                                     "PAST_CUTOFF": BLOCK if comp else WARN}[d.phase],
                           f"{d.phase}, {d.minutes_left:.0f} min to cutoff {d.cutoff:%m-%d %H:%M}")
    # git
    from agent.ops.preflight import git_info
    g = git or git_info()
    comps["git"] = Check("git", PASS if not g["dirty_paths"] else (BLOCK if comp else WARN),
                         f"git:{g['sha']} {g['branch']}" + (f" dirty {g['dirty_paths'][:5]}" if g["dirty_paths"] else ""))
    # interrupted runs / locks (Round 06)
    from agent.data.locks import find_locks
    from agent.ops.archive_run import partial_dirs
    parts = partial_dirs(ops_cfg)
    locks = find_locks(ROOT / "data" / "raw") if (ROOT / "data" / "raw").exists() else []
    comps["outputs"] = Check("outputs", WARN if parts or locks else PASS,
                             f"{len(parts)} interrupted .partial folders, {len(locks)} lock files"
                             + (f": {[p.name for p in parts[:3]]}" if parts else ""))
    # submission state: a generated file is not a submission
    from agent.submission.base import get_state
    sub_state = get_state(trade_date, ops_cfg)["state"]
    comps["submission"] = Check("submission", {"SUBMISSION_CONFIRMED": PASS, "READY_TO_SUBMIT": PASS,
                                               "SUBMITTED_UNVERIFIED": WARN, "NOT_READY": WARN if not comp else BLOCK,
                                               "REJECTED": BLOCK, "UNKNOWN": BLOCK}[sub_state], sub_state)
    lvl = worst(c.level for c in comps.values())
    res = {"trade_date": trade_date, "mode": mode, "checked_at": clock.now().isoformat(), "status": LABEL[lvl],
           "components": {k: {"status": LABEL[c.level], "detail": c.detail} for k, c in comps.items()}}
    write_json(logs / "healthcheck.json", res)
    return res


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--mode", choices=["dry-run", "competition"], default="dry-run")
    a = ap.parse_args(argv)
    r = healthcheck(a.date, mode=a.mode)
    for k, c in r["components"].items():
        print(f"[{c['status']:8s}] {k:11s} {c['detail']}")
    print("HEALTH:", r["status"])
    return 0 if r["status"] != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
