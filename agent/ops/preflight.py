"""Preflight checks -> PASS / WARN / BLOCK per item, overall = worst.

  python agent\\ops\\preflight.py --date 2026-10-27 --mode competition

BLOCK examples: dirty git tree in competition mode, D-Plan schema missing, no previous settlement,
reconciliation BLOCK, critical data missing, previous portfolio unrecoverable.
WARN examples: optional data missing (SOX / ADR / night futures), ETF holdings slightly stale.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT, D, load_official_rules, load_universe  # noqa: E402
from agent.ops.common import (BLOCK, PASS, WARN, Check, Clock, load_ops_config, ops_logger, ops_path,  # noqa: E402
                              sha256_file, worst, write_json, ymd)


def git_info() -> dict:
    def run(*a):
        r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=15)
        return r.stdout.strip() if r.returncode == 0 else None
    return {"sha": run("rev-parse", "--short", "HEAD"), "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_paths": [l[3:] for l in (run("status", "--porcelain", "--", "agent", "config") or "").splitlines()]}


def config_hashes(strategy_cfg: str, llm_cfg: str | None) -> dict:
    out = {"strategy": sha256_file(ROOT / strategy_cfg), "competition": sha256_file(ROOT / "config/competition.yaml"),
           "unconfirmed_rules": sha256_file(ROOT / "config/unconfirmed_rules.yaml"),
           "ops": sha256_file(ROOT / "config/ops.yaml")}
    if llm_cfg:
        out["llm"] = sha256_file(ROOT / llm_cfg)
    return out


def prompt_versions() -> dict:
    from agent.llm.client import load_prompt
    return {p.stem: load_prompt(p.stem)[2] for p in sorted((ROOT / "agent/llm/prompts").glob("*.txt"))}


def previous_portfolio_check(holdings: dict, cash, closes: dict, rb) -> Check:
    """Is the previous (settled) portfolio still legal at T-1 close? Detects passive cash drift (Round 04),
    odd lots (stock dividends) and non-universe holdings. Illegal -> the run must TRADE, not fall back."""
    from agent.engine.compliance import check_portfolio
    if not holdings:
        return Check("previous_portfolio_legal", PASS, "no holdings (day 1: all cash, must buy)")
    missing = [t for t in holdings if t not in closes]
    if missing:
        return Check("previous_portfolio_legal", BLOCK, f"no T-1 close for held tickers {missing}")
    rep = check_portfolio(holdings, closes, D(cash), rb, "前日持股(T-1收盤)")
    fails = [c.message for c in rep.failures]
    warns = [c.message for c in rep.checks if c.status.value == "WARNING"]
    if fails:
        return Check("previous_portfolio_legal", WARN,
                     "previous portfolio is NOT legal at T-1 close -> plain fallback is unsafe, run must rebalance: "
                     + "; ".join(fails)[:400])
    return Check("previous_portfolio_legal", PASS if not warns else WARN, "; ".join(warns)[:300] or "legal")


def run_preflight(trade_date: str, *, mode: str = "dry-run", strategy_cfg: str = "config/strategy_quant_v1.yaml",
                  llm_cfg: str | None = None, clock: Clock | None = None, ops_cfg: dict | None = None,
                  data_health: dict | None = None, settlement_status: dict | None = None,
                  prev_holdings: dict | None = None, prev_cash=None, closes_prev: dict | None = None,
                  git: dict | None = None, extra: list[Check] | None = None, store=None, llm_provider=None) -> dict:
    ops_cfg = ops_cfg or load_ops_config()
    clock = clock or Clock()
    pf = ops_cfg["preflight"]
    checks: list[Check] = []
    comp = mode == "competition"
    # ---- code / config
    g = git or git_info()
    if g["dirty_paths"]:
        checks.append(Check("git_clean", BLOCK if comp else WARN, f"dirty: {g['dirty_paths'][:8]}"))
    else:
        checks.append(Check("git_clean", PASS, f"git:{g['sha']}"))
    checks.append(Check("git_branch", PASS if g["branch"] == pf["branch"] else WARN, str(g["branch"])))
    try:
        hashes = config_hashes(strategy_cfg, llm_cfg)
        checks.append(Check("config_hashes", PASS, json.dumps({k: v[7:19] for k, v in hashes.items()})))
    except FileNotFoundError as e:
        hashes = {}
        checks.append(Check("config_hashes", BLOCK, str(e)))
    fz = ops_cfg.get("freeze") or {}
    if fz and Path(strategy_cfg).as_posix() == fz["strategy_config"]:
        same = hashes.get("strategy") == fz["strategy_sha256"]
        checks.append(Check("strategy_freeze", PASS if same else (BLOCK if comp else WARN),
                            f"matches freeze {fz['frozen_in_commit']}" if same else
                            "strategy config differs from STRATEGY_FREEZE_RECORD (unreviewed change?)"))
    elif comp:
        checks.append(Check("strategy_freeze", WARN, f"competition run with non-frozen config {strategy_cfg}"))
    rules = load_official_rules()
    checks.append(Check("dplan_schema", PASS if rules.schema_path.exists() else BLOCK, str(rules.schema_path.name)))
    uni = load_universe()
    checks.append(Check("universe_150", PASS if len(uni) == 150 else BLOCK, f"{len(uni)} tickers"))
    try:
        pv = prompt_versions()
        checks.append(Check("prompt_versions", PASS, ", ".join(pv.values())))
    except Exception as e:  # noqa: BLE001
        pv = {}
        checks.append(Check("prompt_versions", WARN, str(e)))
    # ---- environment
    checks.append(Check("python_version", PASS if tuple(map(int, platform.python_version().split(".")[:2]))
                        >= tuple(map(int, pf["python_min"].split("."))) else BLOCK, platform.python_version()))
    missing = [m for m in ("pandas", "numpy", "pyarrow", "jsonschema", "pydantic", "yaml", "requests", "httpx")
               if importlib.util.find_spec(m) is None]
    checks.append(Check("dependencies", BLOCK if missing else PASS, f"missing {missing}" if missing else "ok"))
    free_gb = shutil.disk_usage(ROOT).free / 2**30
    checks.append(Check("disk_space", PASS if free_gb >= pf["min_free_disk_gb"] else BLOCK, f"{free_gb:.1f} GB free"))
    now = clock.now()
    checks.append(Check("system_time", PASS if now.utcoffset().total_seconds() == 8 * 3600 else WARN, now.isoformat()))
    try:
        from agent.ops.deadline import cutoff_for, opening_for
        c, o = cutoff_for(trade_date), opening_for(trade_date)
        inwin = o <= now <= c
        checks.append(Check("submission_window", PASS if inwin or not comp else WARN,
                            f"now {now:%m-%d %H:%M}, window {o:%m-%d %H:%M}–{c:%m-%d %H:%M}"))
        checks.append(Check("pit_cutoff", PASS, f"decision data as of {now.isoformat()} (< cutoff {c.isoformat()})"
                            if now < c else f"now is past cutoff {c.isoformat()}"))
    except Exception as e:  # noqa: BLE001
        checks.append(Check("submission_window", WARN, str(e)))
    # ---- data
    if data_health is None:
        p = ops_path(ops_cfg, "ops_logs_dir") / ymd(trade_date) / "data_health.json"
        data_health = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    if data_health is None:
        checks.append(Check("data_freshness", WARN, "no data_health report for this trade date (refresh not run)"))
    else:
        for s in data_health["sources"]:
            bad = s["status"] in ("FAILED", "STALE")
            if s["status"] == "SKIPPED":
                lvl = WARN if s["criticality"] == "CRITICAL" else PASS
            elif s["status"] == "CACHED":
                lvl = WARN                       # source unreachable, required rows already in the store
            elif not bad:
                lvl = PASS
            else:
                lvl = {"CRITICAL": BLOCK, "IMPORTANT": WARN, "OPTIONAL": WARN}[s["criticality"]]
            checks.append(Check(f"data:{s['source']}", lvl,
                                f"{s['status']} latest={s['latest_available_date']} {s['error'] or ''}"[:200]))
    # ETF holdings freshness (store-level, real rows only)
    try:
        from agent.data.loaders import HistoryStore
        e = (store or HistoryStore()).load("etf_holdings")
        e = e[~e["synthetic"]]
        e = e[e["date"] < trade_date]          # PIT: never judge freshness with data after the trade date
        if len(e):
            newest = e.groupby("etf")["date"].max()
            age = (date.fromisoformat(trade_date) - date.fromisoformat(newest.min())).days
            lvl = PASS if age <= pf["etf_stale_days_warn"] else (WARN if age <= pf["etf_stale_days_block"] else BLOCK)
            checks.append(Check("etf_holdings_freshness", lvl,
                                f"{newest.size} ETFs; oldest latest-date {newest.min()} ({age} days)"))
        else:
            checks.append(Check("etf_holdings_freshness", WARN, "no real ETF holdings in store"))
    except Exception as ex:  # noqa: BLE001
        checks.append(Check("etf_holdings_freshness", WARN, str(ex)))
    # ---- settlement
    ss = settlement_status or {}
    if not ss.get("previous_available"):
        checks.append(Check("settlement_available", BLOCK if not ss.get("initial_day") else PASS,
                            "initial day (cash only)" if ss.get("initial_day") else "no previous settlement"))
    else:
        checks.append(Check("settlement_available", PASS, ss.get("source", "")))
    rec = ss.get("reconciliation")
    if ss.get("initial_day"):
        checks.append(Check("settlement_reconciled", PASS, "initial day"))
    elif rec is None or rec == "UNAVAILABLE":
        need = comp and pf["require_official_settlement_in_competition"]
        checks.append(Check("settlement_reconciled", BLOCK if need else WARN,
                            "official settlement not available / not reconciled"))
    else:
        checks.append(Check("settlement_reconciled", {"MATCH": PASS, "MINOR_DIFFERENCE": WARN, "BLOCK": BLOCK}[rec], rec))
    if prev_holdings is not None and closes_prev is not None:
        from agent.engine.rules import load_rulebook
        checks.append(previous_portfolio_check(prev_holdings, prev_cash, closes_prev, load_rulebook()))
    # ---- LLM
    if llm_cfg:
        from agent.llm.client import load_llm_config, make_provider
        lc = load_llm_config(llm_cfg)
        try:
            pr = llm_provider if llm_provider is not None else make_provider(lc)   # Round 07: the real instance
            ok = pr.name != "template" and pr.available()
            checks.append(Check("llm_availability", PASS if ok else WARN,
                                f"{pr.name} {'available' if ok else 'unavailable -> template narrative'}"))
        except Exception as e:  # noqa: BLE001
            checks.append(Check("llm_availability", WARN, f"{e} -> template narrative"))
    else:
        checks.append(Check("llm_availability", PASS, "template narrative (no LLM configured)"))
    checks += extra or []
    res = {"trade_date": trade_date, "mode": mode, "checked_at": now.isoformat(),
           "level": worst(c.level for c in checks), "checks": [c.to_dict() for c in checks],
           "git": g, "config_hashes": hashes, "prompt_versions": pv}
    write_json(ops_path(ops_cfg, "ops_logs_dir") / ymd(trade_date) / "preflight.json", res)
    lg = ops_logger(trade_date, "preflight", ops_cfg)
    for c in checks:
        lg.info(f"{c.level:5s} {c.name}: {c.detail}")
    return res


def ledger_settlement_status(trade_date: str, ops_cfg: dict | None = None, initial: bool = False):
    """Standalone preflight: settlement status of T-1 from the ledger (internal + official, reconciled)."""
    from agent.data.loaders import HistoryStore
    from agent.ops.reconcile import reconcile
    from agent.ops.settlement import ManualFileSettlementProvider, load_internal
    from agent.sim.calendar import TradingCalendar
    ops_cfg = ops_cfg or load_ops_config()
    store = HistoryStore()
    prev = TradingCalendar(store.dates("daily_prices") + [trade_date]).prev(trade_date)
    if initial:
        return {"previous_date": prev, "initial_day": True, "previous_available": True, "source": "initial cash"}, None, None
    internal = load_internal(prev, ops_cfg) if prev else None
    official = ManualFileSettlementProvider(ops_cfg).get(prev) if prev else None
    st = {"previous_date": prev, "previous_available": internal is not None or official is not None,
          "source": "internal+official" if internal and official else ("internal" if internal else
                                                                     ("official" if official else None))}
    if internal is not None and official is not None:
        st["reconciliation"] = reconcile({"holdings": internal.holdings, "cash": str(internal.cash),
                                          "nav": str(internal.nav), "accrued_dividends": str(internal.accrued_dividends),
                                          "warnings": [w["rule"] for w in internal.warnings]}, official, ops_cfg)["status"]
    else:
        st["reconciliation"] = "UNAVAILABLE"
    closes = {}
    if internal is not None and prev:
        p = store.load("daily_prices")
        p = p[p["date"] == prev]
        closes = {r.ticker: D(round(float(r.close), 4)) for r in p.itertuples() if r.close == r.close}
    return st, internal, closes


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--mode", choices=["dry-run", "competition"], default="dry-run")
    ap.add_argument("--config", default="config/strategy_quant_v1.yaml")
    ap.add_argument("--llm-config", default=None)
    ap.add_argument("--initial", action="store_true", help="first competition day (start from cash)")
    ap.add_argument("--competition-profile", choices=["prod"], default=None,
                    help="also report the profile's LLM runtime (Claude CLI version pin + auth); never blocks")
    a = ap.parse_args(argv)
    st, internal, closes = ledger_settlement_status(a.date, initial=a.initial)
    r = run_preflight(a.date, mode=a.mode, strategy_cfg=a.config, llm_cfg=a.llm_config, settlement_status=st,
                      prev_holdings=internal.holdings if internal else None,
                      prev_cash=internal.cash if internal else None, closes_prev=closes if internal else None)
    for c in r["checks"]:
        print(f"[{c['level']:5s}] {c['name']:28s} {c['detail']}")
    print("PREFLIGHT:", r["level"])
    if a.competition_profile:                          # Round 07: LLM is optional -> printed, never a BLOCK
        from agent.competition_day import llm_runtime_status, load_competition_profile
        from agent.llm.client import load_llm_config
        prof = load_competition_profile(a.competition_profile)
        prov = None
        if prof["llm"]["primary"] == "claude-cli":
            from agent.llm.providers.claude_cli import ClaudeCodeCLIProvider
            prov = ClaudeCodeCLIProvider(None, dict(load_llm_config(prof["llm"]["config"]), enabled=True))
        st = llm_runtime_status(prov)
        print(f"[{'PASS' if st['status'] in ('READY', 'TEMPLATE') else 'WARN':5s}] {'llm_runtime':28s} "
              f"binary={st.get('binary', '-')} version={st.get('version', '-')} ({st.get('version_check', '-')}) "
              f"auth={st.get('authMethod', '-')} profile={st.get('profile', '-')}")
        print(st["line"])
    return 0 if r["level"] != BLOCK else 2


if __name__ == "__main__":
    raise SystemExit(main())
