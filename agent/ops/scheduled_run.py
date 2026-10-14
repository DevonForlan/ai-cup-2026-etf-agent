"""Daily 19:30 PRECOMPETITION dry-run with missed-run catch-up (Windows Task Scheduler helper).

Called by automation/run_precompetition_scheduled.ps1 (task AI_CUP_Precompetition_DryRun_1930,
WakeToRun=False, StartWhenAvailable=True). Never uploads, never logs in anywhere, never changes strategy or
gates: it only runs the already-validated command

    agent/competition_day.py --date T --team-id <config> --mode dry-run --competition-profile prod --initial

and records the outcome in logs/scheduled/ (latest_status.json, history.jsonl, one .log per run).

Date rules (submission window = calendar day before T, 19:30 -> T 08:55; config/competition.yaml):
  * the run belongs to the scheduled date D = today if now >= 19:30, else yesterday (a catch-up after midnight);
  * D is the run date only if now is still on D (same calendar day); a start after midnight for yesterday's
    19:30 -> MISSED_PREVIOUS_DAY (recorded, never run: no stale-date / next-day-data mix-up);
  * T = D + 1 calendar day must be a trading day (weekends + config/ops.yaml market_holidays), otherwise no
    window opens tonight -> SKIPPED (NO_SUBMISSION_WINDOW_TONIGHT);
  * D already has a PASS -> SKIPPED (SKIP_ALREADY_PASSED); BLOCKED / FAILED -> may run again.
Statuses: PASS | BLOCKED | FAILED | SKIPPED.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.ops.common import TPE, load_ops_config, ymd  # noqa: E402

LOG_DIR = ROOT / "logs" / "scheduled"
LATEST = LOG_DIR / "latest_status.json"
HISTORY = LOG_DIR / "history.jsonl"
TASK_NAME = "AI_CUP_Precompetition_DryRun_1930"
STATUSES = ("PASS", "BLOCKED", "FAILED", "SKIPPED")
NETWORK_TARGETS = [("DNS", "www.twse.com.tw"), ("HTTPS", "https://www.google.com/"),
                   ("ESUN", "https://esun-ai-challenge.tw/"),
                   ("TWSE", "https://www.twse.com.tw/zh/"), ("TPEX", "https://www.tpex.org.tw/")]
LOG_KEYS = ["LABEL", "RUN_MODE", "DATAPACK_STATUS", "DATAPACK_DATE", "DATAPACK_FILE", "SETTLEMENT_SOURCE",
            "PAPER_CHAIN", "SCHEDULED_TIME", "ACTUAL_START_TIME", "RUN_DELAY_MINUTES", "TRADE_DATE", "NETWORK", "NETWORK_RETRIES",
            "CLAUDE_VERSION", "CLAUDE_STATUS", "DATA_REFRESH", "ETF_FRESHNESS", "QUANT", "ACTIVE_SHARE", "GROUNDING",
            "DPLAN_VERSION", "DPLAN_VALIDATION", "FINAL_CANDIDATE", "OVERALL_STATUS", "BLOCKED_REASON",
            "ERROR_MESSAGE", "END_TIME"]


# ----------------------------------------------------------------------------- pure date logic (unit tested)
def window_open_time() -> tuple[int, int]:
    from agent.config import load_official_rules
    hh, mm = map(int, load_official_rules().submission_open.split(":"))
    return hh, mm


def holidays(ops_cfg: dict | None = None) -> set[str]:
    return {str(x) for x in (ops_cfg or load_ops_config()).get("market_holidays") or []}


def is_trading_day(d: date, hol: set[str]) -> bool:
    return d.weekday() < 5 and d.isoformat() not in hol


def plan(now: datetime, hol: set[str], open_hm: tuple[int, int] = (19, 30)) -> dict:
    """Which scheduled run this start belongs to and whether it may run. Pure function."""
    today = now.date()
    today_open = datetime(today.year, today.month, today.day, *open_hm, tzinfo=TPE)
    sched_day = today if now >= today_open else today - timedelta(days=1)
    sched = datetime(sched_day.year, sched_day.month, sched_day.day, *open_hm, tzinfo=TPE)
    trade = sched_day + timedelta(days=1)
    out = {"scheduled_date": sched_day.isoformat(), "scheduled_time": sched.isoformat(),
           "actual_start_time": now.replace(microsecond=0).isoformat(),
           "run_delay_minutes": int((now - sched).total_seconds() // 60), "trade_date": trade.isoformat(),
           "action": "RUN", "reason": None}
    if sched_day != today:
        out.update(action="SKIP", reason="MISSED_PREVIOUS_DAY")
    elif not is_trading_day(trade, hol):
        out.update(action="SKIP", reason="NO_SUBMISSION_WINDOW_TONIGHT", trade_date=None)
    return out


def prev_trading_day(d: date, hol: set[str]) -> date:
    x = d - timedelta(days=1)
    while not is_trading_day(x, hol):
        x -= timedelta(days=1)
    return x


def next_trading_day(d: date, hol: set[str]) -> date:
    x = d + timedelta(days=1)
    while not is_trading_day(x, hol):
        x += timedelta(days=1)
    return x


def missing_trading_days(trade_date: str, stored: set[str], hol: set[str], lookback_days: int = 15) -> list[str]:
    """Trading days in the last `lookback_days` calendar days before T that are not in the price store
    (e.g. the laptop was off for several days: the daily refresh only fetches T-1)."""
    t = date.fromisoformat(trade_date)
    out, d = [], t - timedelta(days=lookback_days)
    first = min(stored) if stored else None
    while d < t:
        if is_trading_day(d, hol) and d.isoformat() not in stored and (first is None or d.isoformat() > first):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def already_passed(scheduled_date: str, history: list[dict]) -> bool:
    return any(h.get("scheduled_date") == scheduled_date and h.get("status") == "PASS" for h in history)


# ----------------------------------------------------------------------------- io helpers
def read_history() -> list[dict]:
    if not HISTORY.exists():
        return []
    out = []
    for line in HISTORY.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    try:
        latest = json.loads(LATEST.read_text(encoding="utf-8")) if LATEST.exists() else None
    except ValueError:
        latest = None
    return out + ([latest] if latest else [])


class RunLog:
    def __init__(self, started: datetime):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.path = LOG_DIR / f"precompetition_dryrun_{started:%Y%m%d_%H%M%S}.log"

    def w(self, key: str, value) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"{key:<20} {value}\n")


def network_check(retries: int = 5, wait_sec: float = 30.0, log: RunLog | None = None, probe=None) -> dict:
    """DNS + HTTPS + esun site + at least one of TWSE / TPEx. Up to `retries` retries, `wait_sec` apart."""
    probe = probe or _probe
    res = {}
    for attempt in range(retries + 1):
        res = {name: probe(name, target) for name, target in NETWORK_TARGETS}
        ok = res["DNS"] and res["HTTPS"] and res["ESUN"] and (res["TWSE"] or res["TPEX"])
        if ok:
            return {"ok": True, "retries": attempt, "detail": res}
        if attempt < retries:
            if log:
                log.w(f"NETWORK_RETRY_{attempt + 1}", " ".join(f"{k}={'OK' if v else 'FAIL'}" for k, v in res.items()))
            time.sleep(wait_sec)
    return {"ok": False, "retries": retries, "detail": res}


def _probe(name: str, target: str) -> bool:
    try:
        if name == "DNS":
            socket.getaddrinfo(target, 443)
            return True
        req = urllib.request.Request(target, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status < 500
    except Exception:  # noqa: BLE001
        return False


def claude_check() -> dict:
    """Whitelisted status only (version + loggedIn/authMethod via the project's provider); no tokens."""
    try:
        from agent.competition_day import llm_runtime_status
        from agent.llm.client import load_llm_config
        from agent.llm.providers.claude_cli import ClaudeCodeCLIProvider
        prov = ClaudeCodeCLIProvider(None, dict(load_llm_config("config/llm_claude_cli.yaml"), enabled=True))
        st = llm_runtime_status(prov)
        return {"ready": st["status"] == "READY", "version": st.get("version"), "version_check": st.get("version_check"),
                "line": st["line"]}
    except Exception as e:  # noqa: BLE001
        return {"ready": False, "version": None, "version_check": None, "line": f"ERROR {type(e).__name__}"}


def summarize(summary: dict | None, preflight: dict | None, rc: int) -> dict:
    """competition_day summary -> scheduled status fields. Never reinterprets a gate."""
    if not summary:
        return {"status": "FAILED", "error_message": f"no competition_day summary (exit code {rc})"}
    st = summary.get("status")
    checks = (preflight or {}).get("checks") or []
    etf = next((c for c in checks if c["name"] == "etf_holdings_freshness"), None)
    cs = summary.get("compliance_summary") or {}
    llm = summary.get("llm") or {}
    out = {"cd_status": st,
           "data_refresh": summary.get("data_health", "NOT_RUN"),
           "etf_freshness": f"{etf['level']} {etf['detail']}" if etf else "UNKNOWN",
           "quant": "PASS" if summary.get("decisions") is not None else "NOT_RUN",
           "active_share": cs.get("Active Share official >= 15%", "NOT_RUN"),
           "grounding": ("PASS" if llm.get("used") and not llm.get("failed") else
                         "TEMPLATE_FALLBACK" if llm.get("calls") is not None else "NOT_RUN"),
           "dplan_validation": summary.get("validation") or "NOT_RUN",
           "final_candidate": summary.get("final_file"),
           "settlement_source": (summary.get("settlement_source") or {}).get("settlement_source"),
           "settlement_date": (summary.get("settlement_source") or {}).get("settlement_date"),
           "blocked_reason": None, "error_message": None}
    if st in ("DRY_RUN_OK", "READY_TO_SUBMIT", "HISTORICAL_OK"):
        out["status"] = "PASS"
    elif st in ("BLOCKED", "LATE_PAST_CUTOFF"):
        r = str(summary.get("reason") or "")
        out["status"] = "BLOCKED"
        dp_reason = next((x for x in ("DATAPACK_MISSING", "DATAPACK_STALE", "DATAPACK_INVALID") if r.startswith(x)), None)
        out["blocked_reason"] = (dp_reason if dp_reason else
                                 "ETF_HOLDINGS_STALE" if "etf_holdings_freshness" in r else
                                 "LATE_PAST_CUTOFF" if st == "LATE_PAST_CUTOFF" else
                                 "SUBMISSION_WINDOW_NOT_OPEN" if "submission_window_open" in r else
                                 "PREFLIGHT_BLOCK: " + r[:200])
    else:
        out["status"] = "FAILED"
        out["error_message"] = f"competition_day status {st}: {str(summary.get('reason'))[:300]}"
    return out


def finish(rec: dict, log: RunLog) -> dict:
    rec["finished_at"] = datetime.now(TPE).replace(microsecond=0).isoformat()
    rec["log_file"] = str(log.path)
    assert rec["status"] in STATUSES
    for k in LOG_KEYS:
        v = {"LABEL": rec.get("label") or "PRECOMPETITION_PAPER_RUN", "RUN_MODE": rec.get("run_mode"),
             "DATAPACK_STATUS": rec.get("datapack_status"), "DATAPACK_DATE": rec.get("datapack_date"),
             "DATAPACK_FILE": rec.get("datapack_file"), "SETTLEMENT_SOURCE": rec.get("settlement_source"),
             "PAPER_CHAIN": rec.get("paper_chain"),
             "SCHEDULED_TIME": rec.get("scheduled_time"), "ACTUAL_START_TIME": rec.get("actual_start_time"),
             "RUN_DELAY_MINUTES": rec.get("run_delay_minutes"), "TRADE_DATE": rec.get("trade_date"),
             "NETWORK": rec.get("network"), "NETWORK_RETRIES": rec.get("network_retries"),
             "CLAUDE_VERSION": rec.get("claude_version"), "CLAUDE_STATUS": rec.get("claude"),
             "DATA_REFRESH": rec.get("data_refresh"), "ETF_FRESHNESS": rec.get("etf_freshness"),
             "QUANT": rec.get("quant"), "ACTIVE_SHARE": rec.get("active_share"), "GROUNDING": rec.get("grounding"),
             "DPLAN_VERSION": rec.get("dplan_version"), "DPLAN_VALIDATION": rec.get("dplan_validation"),
             "FINAL_CANDIDATE": rec.get("final_candidate"), "OVERALL_STATUS": rec["status"],
             "BLOCKED_REASON": rec.get("blocked_reason"), "ERROR_MESSAGE": rec.get("error_message"),
             "END_TIME": rec["finished_at"]}[k]
        log.w(k, v if v is not None else "-")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LATEST.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def run(now: datetime | None = None, setup_test: bool = False, net_retries: int = 5, net_wait: float = 30.0) -> dict:
    now = now or datetime.now(TPE)
    log = RunLog(now)
    p = plan(now, holidays(), window_open_time())
    rec = {k: None for k in ("network", "network_retries", "claude", "claude_version", "claude_fallback",
                             "data_refresh", "etf_freshness", "quant", "active_share", "grounding", "dplan_version",
                             "dplan_validation", "final_candidate", "blocked_reason", "error_message",
                             "datapack_status", "datapack_date", "datapack_source", "datapack_file",
                             "settlement_source", "settlement_date")}
    rec["run_mode"] = run_mode()
    rec.update({k: p[k] for k in ("scheduled_date", "scheduled_time", "actual_start_time", "run_delay_minutes",
                                  "trade_date")}, mode="SETUP_TEST_MODE" if setup_test else "PRECOMPETITION_REAL_DATA_DRY_RUN")
    log.w("MODE", rec["mode"])
    if p["action"] == "SKIP" and not setup_test:
        rec.update(status="SKIPPED", blocked_reason=p["reason"])
        return finish(rec, log)
    if not setup_test and already_passed(p["scheduled_date"], read_history()):
        rec.update(status="SKIPPED", blocked_reason="SKIP_ALREADY_PASSED")
        return finish(rec, log)
    net = network_check(net_retries, net_wait, log)
    rec.update(network="OK" if net["ok"] else "FAIL " + json.dumps(net["detail"]), network_retries=net["retries"])
    cl = claude_check()
    rec.update(claude="READY" if cl["ready"] else "NOT_READY (template fallback)", claude_version=
               f"{cl['version']} {cl['version_check']}", claude_fallback=not cl["ready"])
    log.w("CLAUDE_LINE", cl["line"])
    if not net["ok"]:
        rec.update(status="BLOCKED", blocked_reason="NETWORK_UNAVAILABLE")
        return finish(rec, log)
    if setup_test:                       # scheduler / logging / network / Claude context only — never a real PASS
        rec.update(status="SKIPPED", blocked_reason="SETUP_TEST_MODE (no dry-run executed)")
        return finish(rec, log)
    from agent.config import load_strategy
    team = load_strategy("config/strategy_quant_v1.yaml")["team_id"]
    mode = run_mode()
    rec["run_mode"] = mode
    rec["data_backfill"] = backfill_gaps(p["trade_date"], log)
    pre = competition_preparation(mode, p["trade_date"], team, log)
    rec.update({k: pre[k] for k in ("label", "datapack_status", "datapack_date", "datapack_source", "datapack_file",
                                    "paper_chain", "settlement_source")})
    if pre["blocked_reason"]:
        rec.update(status="BLOCKED", blocked_reason=pre["blocked_reason"], error_message=pre.get("detail"))
        return finish(rec, log)
    cmd = [sys.executable, str(ROOT / "agent" / "competition_day.py"), "--date", p["trade_date"], "--team-id", team,
           "--mode", pre["cd_mode"], "--competition-profile", "prod"] + pre["extra_args"]
    log.w("COMMAND", " ".join(cmd[1:]))
    rc, err = None, None
    try:
        cp = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=100 * 60)
        rc = cp.returncode
        (LOG_DIR / (log.path.stem + "_competition_day.txt")).write_text(cp.stdout[-20000:] + cp.stderr[-5000:],
                                                                         encoding="utf-8")
    except subprocess.TimeoutExpired:
        err = "competition_day timeout (100 min)"
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    ops = load_ops_config()
    day = ROOT / ops["paths"]["ops_logs_dir"] / ymd(p["trade_date"])
    summary = preflight = None
    try:
        s = json.loads((day / "competition_day_summary.json").read_text(encoding="utf-8"))
        if s.get("started_at", "") >= rec["actual_start_time"][:16]:        # this run's summary, not an older one
            summary = s
        preflight = json.loads((day / "preflight.json").read_text(encoding="utf-8")) if (day / "preflight.json").exists() else None
    except (OSError, ValueError):
        pass
    rec.update(summarize(summary, preflight, rc if rc is not None else -1))
    if err:
        rec.update(status="FAILED", error_message=err)
    rec.pop("cd_status", None)
    if rec.get("final_candidate"):
        try:
            fp = ROOT / rec["final_candidate"]
            rec["dplan_version"] = json.loads(fp.read_text(encoding="utf-8")).get("schema_version")
        except (OSError, ValueError):
            pass
    if rec.get("status") == "PASS" and mode == "PRECOMPETITION":
        try:
            from agent.ops.prediction_summary import build
            rec["prediction_summary"] = str(build(p["trade_date"], run_summary=summary))
        except Exception as e:  # noqa: BLE001
            rec["prediction_summary"] = f"ERROR {type(e).__name__}: {str(e)[:200]}"
    return finish(rec, log)


def run_mode(ops_cfg: dict | None = None) -> str:
    m = str((ops_cfg or load_ops_config()).get("run_mode") or "PRECOMPETITION").upper()
    if m not in ("PRECOMPETITION", "COMPETITION"):
        raise ValueError(f"config/ops.yaml run_mode {m!r} must be PRECOMPETITION or COMPETITION")
    return m


def competition_preparation(mode: str, trade_date: str, team: str, log: RunLog, provider=None,
                            ops_cfg: dict | None = None) -> dict:
    """PRECOMPETITION: DataPack NOT_REQUIRED, paper ledger (or initial capital) as the starting point.
    COMPETITION: official DataPack REQUIRED via the gate; missing / stale / invalid -> BLOCKED, NO fallback to
    the paper ledger, internal settlement, estimates or the previous prediction."""
    out = {"label": None, "datapack_status": None, "datapack_date": None, "datapack_source": None,
           "datapack_file": None, "paper_chain": None, "settlement_source": None, "blocked_reason": None,
           "detail": None, "cd_mode": None, "extra_args": []}
    if mode == "COMPETITION":
        from agent.config import load_official_rules
        from agent.ops.datapack import datapack_gate
        first = str(load_official_rules().raw["official_rules"].get("first_trade_date") or "")
        initial = trade_date == first
        g = datapack_gate(trade_date, team, provider=provider, initial=initial, ops_cfg=ops_cfg)
        out.update(label="COMPETITION", datapack_status=g["status"] if g["status"] != "PASS" else
                   f"PASS ({g['freshness']})", datapack_date=g["settlement_date"], datapack_source="ManualFileProvider",
                   datapack_file=g["file"], cd_mode="competition",
                   settlement_source="INITIAL_CAPITAL" if initial else "OFFICIAL_DATAPACK",
                   extra_args=["--initial"] if initial else [])
        log.w("DATAPACK_GATE", f"{g['status']} {g.get('reason') or ''} expected {g['expected_previous_trading_day']} "
                               f"file={g['file']}")
        if g["status"] != "PASS":
            out.update(blocked_reason=g["reason"], detail="; ".join(g.get("problems") or [])[:300])
        return out
    start = paper_start(trade_date, log)
    out.update(label="PRECOMPETITION_PAPER_RUN", datapack_status="NOT_REQUIRED", paper_chain=start["source"],
               cd_mode="dry-run",
               settlement_source="PRECOMPETITION_PAPER_LEDGER" if start["source"].startswith("CHAIN") else "INITIAL_CAPITAL",
               extra_args=["--replay-run", start["ledger"]] if start["source"].startswith("CHAIN") else ["--initial"])
    return out


def backfill_gaps(trade_date: str, log: RunLog) -> list[str]:
    """Fetch missing trading days (prices / institutional / corporate actions) from the same public sources."""
    try:
        from agent.data.loaders import HistoryStore
        from agent.ops.refresh_daily import refresh
        hol = holidays()
        gaps = missing_trading_days(trade_date, set(HistoryStore().dates("daily_prices")), hol)
        for g in gaps:
            refresh(next_trading_day(date.fromisoformat(g), hol).isoformat(),
                    only={"twse_prices", "tpex_prices", "twse_institutional", "tpex_institutional", "corporate_actions"})
        log.w("DATA_BACKFILL", ",".join(gaps) or "none")
        return gaps
    except Exception as e:  # noqa: BLE001
        log.w("DATA_BACKFILL", f"ERROR {type(e).__name__}: {str(e)[:200]}")
        return [f"ERROR {type(e).__name__}"]


def paper_start(trade_date: str, log: RunLog) -> dict:
    """Paper chain: start from the paper ledger settlement of the previous trading day; if missing but a
    prediction for that day exists, evaluate it first (17:00 task may not have run yet); otherwise reset
    the paper portfolio to initial cash (recorded)."""
    from agent.ops import daily_evaluation as DE
    paths = DE.Paths()
    prev = prev_trading_day(date.fromisoformat(trade_date), holidays()).isoformat()
    if not paths.settlement(prev).exists():
        from agent.ops.package_submission import active_final
        if active_final(prev) is not None:
            r = DE.run(ev_date=prev, paths=paths)
            log.w("INLINE_EVALUATION", f"{prev} {r['status']} {r.get('blocked_reason') or ''}")
    if paths.settlement(prev).exists():
        log.w("PAPER_CHAIN", f"CHAIN from paper ledger {prev}")
        return {"source": f"CHAIN:{prev}", "ledger": str(paths.ledger)}
    log.w("PAPER_CHAIN", f"RESET_INITIAL (no paper settlement for {prev})")
    return {"source": f"RESET_INITIAL:no_paper_settlement_{prev}", "ledger": None}


# ----------------------------------------------------------------------------- check (for the operator)
def check(now: datetime | None = None, latest: dict | None = None) -> dict:
    """MISSED when today's run should have happened (after 19:30, window tonight) but no record exists."""
    now = now or datetime.now(TPE)
    p = plan(now, holidays(), window_open_time())
    latest = latest if latest is not None else (json.loads(LATEST.read_text(encoding="utf-8")) if LATEST.exists() else None)
    due_today = p["action"] == "RUN"
    if due_today and (not latest or latest.get("scheduled_date") != p["scheduled_date"]):
        return {"status": "MISSED", "latest": latest, "recommended_action": "MANUAL_RERUN_RECOMMENDED",
                "scheduled_time": p["scheduled_time"]}
    st = (latest or {}).get("status", "NONE")
    rec = "MANUAL_RERUN_RECOMMENDED" if st in ("BLOCKED", "FAILED") else "NONE"
    if st == "SKIPPED" and (latest or {}).get("blocked_reason", "").startswith("SETUP_TEST") and due_today:
        rec = "MANUAL_RERUN_RECOMMENDED"
    return {"status": st, "latest": latest, "recommended_action": rec, "scheduled_time": p["scheduled_time"]}


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup-test", action="store_true", help="scheduler/logging/network/Claude only; never PASS")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        print(json.dumps(check(), ensure_ascii=False))
        return 0
    rec = run(setup_test=a.setup_test)
    print(f"SCHEDULED_RUN {rec['status']} {rec.get('blocked_reason') or ''} log={rec['log_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
