"""Competition-mode readiness preflight — READ ONLY (never switches run_mode, never edits config, never fetches,
never logs in, never uploads).

    .venv\\Scripts\\python.exe -m agent.ops.competition_preflight [--trade-date 2026-10-27] [--json]

Answers "could the COMPETITION run for trade date T start safely right now?" with one line per item:
  READY    item fine for competition
  WARNING  degraded / operator attention, does not by itself stop a competition run
  BLOCKED  a competition run must not start until fixed
Overall = worst item. The tool evaluates COMPETITION requirements even while config/ops.yaml run_mode is
PRECOMPETITION (that case is a WARNING: the switch is a manual, explicit decision; this tool never makes it).
Output: printed table + logs/ops/competition_preflight/<timestamp>.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.ops.common import TPE, load_ops_config, ops_path, sha256_file  # noqa: E402

READY, WARNING, BLOCKED = "READY", "WARNING", "BLOCKED"
ORDER = {READY: 0, WARNING: 1, BLOCKED: 2}
TASKS = ("AI_CUP_Precompetition_DryRun_1930", "AI_CUP_Precompetition_Evaluation_1700")


def item(name: str, level: str, detail: str, action: str | None = None) -> dict:
    return {"item": name, "level": level, "detail": detail, "action": action}


def _ps_json(script: str):
    """Read-only PowerShell query -> parsed JSON (None if unavailable, e.g. non-Windows test hosts)."""
    try:
        cp = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        out = cp.stdout.strip()
        return json.loads(out) if out else []
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------------------- individual checks
def check_run_mode(ops: dict) -> dict:
    from agent.ops.scheduled_run import run_mode
    m = run_mode(ops)
    if m == "COMPETITION":
        return item("run_mode", READY, "COMPETITION")
    return item("run_mode", WARNING, f"{m} (competition switch is a manual decision; this tool never changes it)",
                "On 10/26 after GO: set config/ops.yaml run_mode: COMPETITION (operator)")


def resolve_team_id() -> tuple[str, str]:
    """The team id a COMPETITION run would use (P-1: config/ops.yaml team.competition_team_id)."""
    from agent.ops.team import resolve
    r = resolve("COMPETITION")
    return str(r["configured_value"] or ""), r["source"]


def check_team_id() -> dict:
    from agent.ops.team import is_placeholder
    team, src = resolve_team_id()
    if is_placeholder(team):
        return item("team_id", BLOCKED, f"TEAM_ID_NOT_CONFIGURED ({team or None!r} at {src})",
                    "set config/ops.yaml team.competition_team_id from the organiser's official notice (never guess)")
    return item("team_id", READY, f"{team} ({src})")


def check_worktree() -> dict:
    from agent.ops.preflight import git_info
    g = git_info()
    if g["dirty_paths"]:
        return item("git_worktree", BLOCKED, f"UNCOMMITTED_WORKTREE: {len(g['dirty_paths'])} paths, e.g. {g['dirty_paths'][:4]}",
                    "commit (or move) the pending changes: competition-mode preflight BLOCKS a dirty tree")
    return item("git_worktree", READY, f"clean at {g['sha']} ({g['branch']})")


def check_calendar(trade_date: str, hol: set[str], ops: dict) -> list[dict]:
    from agent.config import load_official_rules
    from agent.ops.scheduled_run import is_trading_day
    out = []
    ops_hol = {str(x) for x in ops.get("market_holidays") or []}
    diff = sorted(ops_hol ^ hol)
    out.append(item("trading_calendar", READY if not diff else BLOCKED,
                    f"{len(hol)} TWSE weekday closures; ops.yaml market_holidays {'consistent' if not diff else 'DIFFERS: ' + str(diff)}"))
    first = str(load_official_rules().raw["official_rules"].get("first_trade_date") or "")
    td = date.fromisoformat(trade_date)
    lvl = READY if is_trading_day(td, hol) else BLOCKED
    out.append(item("trade_date", lvl, f"T={trade_date} ({'trading day' if lvl == READY else 'NOT a trading day'}); "
                                       f"first competition trade date {first}; T is {'DAY 1' if trade_date == first else ('before competition' if trade_date < first else 'day 2+')}"))
    return out


def check_claude() -> dict:
    from agent.ops.scheduled_run import claude_check
    c = claude_check()
    if c["ready"]:
        lvl = WARNING if "DRIFT" in str(c.get("version_check")) else READY
        return item("claude_cli_auth", lvl, f"{c['line']} version {c['version']} {c['version_check']}",
                    None if lvl == READY else "version drift vs pinned list: template fallback covers failures")
    return item("claude_cli_auth", WARNING, f"{c['line']} -> template narrative fallback (quant unaffected)",
                "claude auth status / re-login by the operator (interactive); never automated")


def check_market_data(store, trade_date: str, hol: set[str]) -> list[dict]:
    from agent.ops.datapack import previous_trading_day
    exp = previous_trading_day(trade_date, hol)
    out = []
    from agent.ops.market_coverage import day_coverage, summary_line
    p = store.load("daily_prices")
    last = max(p["date"])
    cov = day_coverage(store, exp)
    if exp > str(date.today()) or (exp == str(date.today()) and datetime.now(TPE).hour < 15):
        out.append(item("market_data_freshness", WARNING, f"T-1={exp} prices not published yet (latest {last})",
                        "rerun after 15:00 / at 19:30"))
    elif cov["status"] == "COMPLETE":
        out.append(item("market_data_freshness", READY, "coverage " + summary_line(cov)))
    else:
        out.append(item("market_data_freshness", BLOCKED, "MARKET_DATA_INCOMPLETE: " + summary_line(cov),
                        f"refresh: python agent\\ops\\refresh_daily.py --date {trade_date} --only twse_prices,tpex_prices"))
    ins = store.load("institutional")
    li = max(ins["date"])
    ni = int(ins[ins["date"] == exp]["ticker"].nunique())
    out.append(item("institutional_freshness", READY if li >= exp and ni >= 140 else WARNING,
                    f"latest {li}; T-1 coverage {ni}/150", None if li >= exp else "IMPORTANT source: degraded, quant v1 does not use it"))
    rev = store.load("monthly_revenue")
    t = date.fromisoformat(trade_date)
    ym = (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)
    if t.day <= 10:                                         # month M-1 revenue is due by the 10th
        ym = (ym[0], ym[1] - 1) if ym[1] > 1 else (ym[0] - 1, 12)
    cut = f"{trade_date}T07:00:00+08:00"
    vis = rev[rev["available_at"].astype(str) <= cut]
    cov = int(vis[(vis["year"] == ym[0]) & (vis["month"] == ym[1])]["ticker"].nunique())
    out.append(item("monthly_revenue_freshness", READY if cov >= 140 else (WARNING if cov >= 100 else BLOCKED),
                    f"{ym[0]}-{ym[1]:02d} revenue visible before T 07:00 for {cov}/150 tickers"))
    return out


def check_etf(store, trade_date: str, ops: dict) -> list[dict]:
    from agent.ops.active_share_gate import source_status
    s = source_status(store, trade_date, ops, competition=True)
    gate = item("active_share_gate", {"PASS": READY, "WARN": WARNING, "BLOCK": BLOCKED}[s["level"]],
                (f"{s['code']}: " if s["code"] else "") + s["detail"] + " (COMPETITION rules; official >= 15%, target 30%)")
    return [gate] + _etf_detail(store, trade_date, ops)


def _etf_detail(store, trade_date: str, ops: dict) -> list[dict]:
    pf = ops["preflight"]
    e = store.load("etf_holdings")
    e = e[(~e["synthetic"]) & (e["date"] < trade_date)]
    out = []
    if not len(e):
        return [item("etf_benchmark_freshness", BLOCKED, "no real ETF holdings"), item("active_share_source", BLOCKED, "no ETF holdings")]
    newest = e.groupby("etf")["date"].max()
    age = (date.fromisoformat(trade_date) - date.fromisoformat(newest.min())).days
    lvl = READY if age <= pf["etf_stale_days_warn"] else (WARNING if age <= pf["etf_stale_days_block"] else BLOCKED)
    out.append(item("etf_benchmark_freshness", lvl, f"{newest.size} ETFs; newest {newest.max()}, oldest latest-date {newest.min()} ({age} calendar days)"))
    import pandas as pd
    lst = pd.read_csv(ROOT / "config" / "active_etf_list.csv", dtype=str, encoding="utf-8-sig")
    covered = len(set(newest.index) & set(lst.iloc[:, 0]))
    out.append(item("active_share_source", READY if covered == len(lst) else WARNING,
                    f"{covered}/{len(lst)} listed active ETFs have real holdings (official top-15 Active Share)"))
    return out


def check_datapack(trade_date: str, team: str, ops: dict) -> list[dict]:
    from agent.ops import datapack_status as DS
    from agent.ops.datapack_downloader import PORTAL_STATUS
    out = []
    d = ops_path(ops, "official_datapack_dir")
    out.append(item("official_datapack_dir", READY if d.is_dir() else BLOCKED,
                    f"{d} ({len(list(d.glob('*.json')))} json files)" if d.is_dir() else f"{d} missing"))
    from agent.config import load_official_rules
    first = str(load_official_rules().raw["official_rules"].get("first_trade_date") or "")
    if trade_date < first:
        out.append(item("expected_prior_settlement", READY, f"T={trade_date} is before the first competition trade date "
                        f"{first}: no official DataPack exists yet (PRECOMPETITION paper ledger)"))
        out.append(item("official_portal_provider", READY if PORTAL_STATUS == "DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION" else BLOCKED,
                        PORTAL_STATUS))
        return out
    s = DS.status("COMPETITION", trade_date, team)
    lvl = READY if s["status"] == "READY" else BLOCKED
    out.append(item("expected_prior_settlement", lvl,
                    f"T={trade_date} expects DataPack as of {s['expected_previous_trading_day']}; "
                    f"source={s['settlement_source'] or '-'}; {s['reason'] or 'ok'}",
                    None if lvl == READY else s["recommended_action"]))
    out.append(item("official_portal_provider", READY if PORTAL_STATUS == "DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION" else BLOCKED,
                    PORTAL_STATUS))
    return out


def check_schema() -> dict:
    from agent.config import load_official_rules
    p = load_official_rules().schema_path
    if not p.exists():
        return item("dplan_schema", BLOCKED, f"{p.name} missing")
    v = json.loads(p.read_text(encoding="utf-8"))
    from agent.dplan.exporter import rb_schema_version
    SCHEMA_VERSION = rb_schema_version()
    pat = v.get("properties", {}).get("schema_version", {}).get("pattern", "")
    ok = "4.3" in p.name and str(SCHEMA_VERSION) == "4.3"
    return item("dplan_schema", READY if ok else BLOCKED, f"{p.name}; exporter writes schema_version {SCHEMA_VERSION} (schema pattern {pat})")


def check_writable(ops: dict) -> list[dict]:
    out = []
    for key in ("submissions_dir", "ops_logs_dir", "archive_dir"):
        d = ops_path(ops, key)
        try:
            d.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".preflight_", dir=d)
            os.close(fd)
            os.remove(tmp)
            out.append(item(f"writable:{key}", READY, str(d)))
        except OSError as e:
            out.append(item(f"writable:{key}", BLOCKED, f"{d}: {e}"))
    free = shutil.disk_usage(ROOT).free / 1e9
    out.append(item("disk_space", READY if free >= ops["preflight"]["min_free_disk_gb"] else BLOCKED, f"{free:.1f} GB free"))
    return out


def check_freeze(ops: dict) -> dict:
    fz = ops["freeze"]
    h = sha256_file(ROOT / fz["strategy_config"])
    h = h if h.startswith("sha256:") else "sha256:" + h
    return item("frozen_quant_fingerprint", READY if h == fz["strategy_sha256"] else BLOCKED,
                f"{fz['strategy_config']} {h[:19]}… {'== frozen' if h == fz['strategy_sha256'] else '!= frozen ' + fz['strategy_sha256'][:19]}")


def check_scheduler() -> list[dict]:
    names = ",".join(f"'{t}'" for t in TASKS)
    q = (f"$n=@({names}); Get-ScheduledTask | Where-Object {{ $n -contains $_.TaskName }} | ForEach-Object {{ $i = $_ | Get-ScheduledTaskInfo; "
         "[pscustomobject]@{Name=$_.TaskName; State=[string]$_.State; Start=($_.Triggers | Select-Object -First 1).StartBoundary; "
         "Multi=[string]$_.Settings.MultipleInstances; Catchup=$_.Settings.StartWhenAvailable; LastResult=$i.LastTaskResult; "
         "Next=[string]$i.NextRunTime} } | ConvertTo-Json -Compress")
    r = _ps_json(q)
    if r is None:
        return [item("scheduler", WARNING, "Task Scheduler not queryable on this host")]
    r = r if isinstance(r, list) else [r]
    found = {x["Name"]: x for x in r}
    out = []
    for t in TASKS:
        x = found.get(t)
        if not x:
            out.append(item(f"scheduler:{t}", BLOCKED, "task missing"))
            continue
        ok = x["State"] in ("Ready", "Running") and x["Multi"] == "IgnoreNew" and x["Catchup"]
        out.append(item(f"scheduler:{t}", READY if ok else WARNING,
                        f"{x['State']} start {str(x['Start'])[11:16]} MultipleInstances={x['Multi']} catch-up={x['Catchup']} "
                        f"last result {x['LastResult']} next {x['Next']}"))
    return out


def logical_runs(procs: list[dict]) -> list[dict]:
    """Collapse the Windows venv launcher pair (launcher python.exe -> base python.exe child with the SAME
    command line) into one logical run. Pure function (unit tested)."""
    by_pid = {p["ProcessId"]: p for p in procs}
    return [p for p in procs
            if not (p.get("ParentProcessId") in by_pid and by_pid[p["ParentProcessId"]].get("CommandLine") == p.get("CommandLine"))]


def check_duplicates() -> dict:
    r = _ps_json("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match "
                 "'scheduled_run|competition_day|daily_evaluation' } | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress")
    if r is None:
        return item("duplicate_processes", WARNING, "process list not available")
    r = r if isinstance(r, list) else [r]
    runs = logical_runs(r)
    kinds = {}
    for p in runs:
        k = next(x for x in ("scheduled_run", "competition_day", "daily_evaluation") if x in (p.get("CommandLine") or ""))
        kinds[k] = kinds.get(k, 0) + 1
    dup = {k: v for k, v in kinds.items() if v > 1}
    if dup:
        return item("duplicate_processes", BLOCKED, f"{len(r)} python processes = {len(runs)} logical runs; DUPLICATE {dup}",
                    "investigate before starting another run")
    return item("duplicate_processes", READY, f"{len(r)} python processes = {len(runs)} logical runs {kinds or ''} "
                                               "(venv launcher+child pairs collapsed)")


# ----------------------------------------------------------------------------- orchestration
def run(trade_date: str | None = None, now: datetime | None = None) -> dict:
    from agent.data.loaders import HistoryStore
    from agent.ops.datapack import calendar_holidays
    from agent.ops.datapack_status import next_trade_date
    ops = load_ops_config()
    hol = calendar_holidays()
    now = now or datetime.now(TPE)
    trade_date = trade_date or next_trade_date(now, hol)
    store = HistoryStore()
    team, _ = resolve_team_id()
    items = [check_run_mode(ops), check_team_id(), check_worktree()]
    items += check_calendar(trade_date, hol, ops)
    items.append(check_claude())
    items += check_market_data(store, trade_date, hol)
    items += check_etf(store, trade_date, ops)
    items += check_datapack(trade_date, team, ops)
    items.append(check_schema())
    items += check_writable(ops)
    items.append(check_freeze(ops))
    items += check_scheduler()
    items.append(check_duplicates())
    overall = max((i["level"] for i in items), key=ORDER.get)
    res = {"tool": "competition_preflight", "read_only": True, "checked_at": now.replace(microsecond=0).isoformat(),
           "trade_date": trade_date, "overall": overall, "items": items}
    d = ops_path(ops, "ops_logs_dir") / "competition_preflight"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{now:%Y%m%d_%H%M%S}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def render(res: dict) -> str:
    lines = [f"COMPETITION PREFLIGHT (read-only)  trade_date={res['trade_date']}  checked_at={res['checked_at']}", ""]
    for i in res["items"]:
        lines.append(f"[{i['level']:<7}] {i['item']:<34} {i['detail']}")
        if i["action"] and i["level"] != READY:
            lines.append(f"{'':10}-> {i['action']}")
    lines += ["", f"OVERALL: {res['overall']}"]
    return "\n".join(lines)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--trade-date", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = run(a.trade_date)
    print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else render(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
