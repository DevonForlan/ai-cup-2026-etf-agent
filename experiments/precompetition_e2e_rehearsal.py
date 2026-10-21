"""PRECOMPETITION end-to-end rehearsal + failure injection (isolated; never uploads, never logs in, never submits).

All ops paths (logs/ops, submissions, archive, settlement, official DataPack dir, reports) are redirected to
runtime/e2e_rehearsal/; the real paper ledger is only READ as the starting point. The real price store is used
(and refreshed through the normal public-data refresh, exactly like the 19:30 run).

    .venv\\Scripts\\python.exe experiments\\precompetition_e2e_rehearsal.py --trade-date 2026-10-19
Output: runtime/e2e_rehearsal/rehearsal_result.json
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.competition_day import OK_STATUSES, run_competition_day  # noqa: E402
from agent.config import load_universe  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.ops.common import Clock, load_ops_config  # noqa: E402
from agent.ops.fingerprint import decision_core_hash  # noqa: E402

OUT = ROOT / "runtime" / "e2e_rehearsal"
LEDGER = ROOT / "data" / "paper_ledger"
CLOCK = None      # simulated wall clock (set in main): the scheduled 19:30 context of the window for T


def iso_ops(sub: str) -> dict:
    c = copy.deepcopy(load_ops_config())
    for k, v in c["paths"].items():
        c["paths"][k] = str(OUT / sub / Path(v).name)
    return c


def final_doc(s: dict) -> dict | None:
    f = s.get("final_file")
    if not f:
        return None
    p = Path(f) if Path(f).is_absolute() else ROOT / f
    return json.loads(p.read_text(encoding="utf-8"))


def claude_provider(fault: str | None = None):
    from agent.llm.client import load_llm_config
    from agent.llm.providers.claude_cli import ClaudeCodeCLIProvider
    cfg = dict(load_llm_config("config/llm_claude_cli.yaml"), enabled=True)
    if fault == "timeout":
        cfg["timeout_sec"] = 0.5                     # hard subprocess timeout -> TIMEOUT -> template
    p = ClaudeCodeCLIProvider(None, cfg)
    if fault == "unavailable":
        p._cli = {"path": None, "kind": None, "version": None}     # binary not found -> CLI_NOT_FOUND
    return p


def run_day(T: str, sub: str, *, provider=None, llm_config=None, data_faults=None, skip_refresh=True, store=None,
            ops=None, clock=None):
    ops = ops or iso_ops(sub)
    return run_competition_day(T, "TEAM_TEST", "dry-run", ops_cfg=ops, store=store or HistoryStore(),
                               clock=clock or Clock(CLOCK), skip_refresh=skip_refresh, replay_run=str(LEDGER),
                               llm_provider=provider, llm_config=llm_config, data_faults=data_faults,
                               archive_readonly=False, write_report=False), ops


def validations(doc: dict) -> dict:
    import jsonschema
    from agent.config import load_official_rules
    schema = json.loads(load_official_rules().schema_path.read_text(encoding="utf-8"))
    errs = sorted(e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(doc))[:5]
    uni = set(load_universe()) if callable(load_universe) else set()
    tick = ({d.get("ticker") for d in doc.get("decisions", [])} | {d.get("ticker") for d in doc.get("no_trade_decisions", [])}
            | {o.get("ticker") for o in doc.get("orders", [])})
    bad_t = sorted(t for t in tick if t and uni and t not in uni)
    w = [float(d.get("target_weight", 0)) for d in doc.get("decisions", [])]
    num_ok = all(0 <= x <= 1 for x in w) and sum(w) <= 1.0000001 and all(int(o.get("shares", 0)) > 0 for o in doc.get("orders", []))
    return {"schema_errors": errs, "schema": "PASS" if not errs else "FAIL", "tickers_outside_universe": bad_t,
            "ticker": "PASS" if not bad_t else "FAIL", "numeric": "PASS" if num_ok else "FAIL",
            "sum_target_weight": round(sum(w), 6), "decisions": len(doc.get("decisions", [])),
            "no_trade_decisions": len(doc.get("no_trade_decisions", [])), "orders": len(doc.get("orders", []))}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--trade-date", required=True)
    ap.add_argument("--skip-e2e", action="store_true")
    a = ap.parse_args()
    T = a.trade_date
    global CLOCK
    from agent.ops.datapack import calendar_holidays
    from datetime import date, timedelta
    CLOCK = (date.fromisoformat(T) - timedelta(days=1)).isoformat() + "T19:45:00+08:00"
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    res = {"trade_date": T, "simulated_clock": CLOCK, "isolated_root": str(OUT), "e2e": {}, "faults": {}}
    store = HistoryStore()
    # ------------------------------------------------------------------ E2E: refresh + Claude CLI narrative
    s_llm, ops = run_day(T, "e2e_claude", provider=claude_provider(), llm_config="config/llm_claude_cli.yaml",
                         skip_refresh=False, store=store)
    s_tpl, _ = run_day(T, "e2e_template", store=store)
    d_llm, d_tpl = final_doc(s_llm), final_doc(s_tpl)
    e = {"status_claude_run": s_llm["status"], "status_template_run": s_tpl["status"], "reason": s_llm.get("reason"),
         "data_health": s_llm.get("data_health"), "settlement_source": s_llm.get("settlement_source"),
         "llm": s_llm.get("llm"), "validation": s_llm.get("validation"), "compliance": s_llm.get("compliance_summary"),
         "final_file": s_llm.get("final_file")}
    if d_llm and d_tpl:
        e["decision_core_hash_claude"] = decision_core_hash(d_llm)
        e["decision_core_hash_template"] = decision_core_hash(d_tpl)
        e["claude_changed_decisions"] = e["decision_core_hash_claude"] != e["decision_core_hash_template"]
        e["checks"] = validations(d_llm)
        e["schema_version"] = d_llm.get("schema_version")
    # prediction report (isolated) + evaluation compatibility (prices of T do not exist yet -> expected BLOCKED)
    try:
        from agent.ops.prediction_summary import build
        e["prediction_report"] = str(build(T, ops_cfg=ops, run_summary=s_llm, out_dir=OUT / "reports"))
    except Exception as ex:  # noqa: BLE001
        e["prediction_report"] = f"ERROR {type(ex).__name__}: {ex}"
    try:
        from agent.ops.daily_evaluation import Paths, evaluate
        r = evaluate(T, ops_cfg=ops, store=store, paths=Paths(ledger=OUT / "ledger", reports=OUT / "reports", logs=OUT / "evlogs"))
        e["evaluation_compat"] = {k: r.get(k) for k in ("status", "blocked_reason", "prediction_file", "dplan_version")}
    except Exception as ex:  # noqa: BLE001
        e["evaluation_compat"] = f"ERROR {type(ex).__name__}: {ex}"
    res["e2e"] = e
    base_hash = e.get("decision_core_hash_template")

    # ------------------------------------------------------------------ failure injection
    def fault(name, **kw):
        try:
            kw.setdefault("store", store)
            s, _ = run_day(T, f"fault_{name}", **kw)
            d = final_doc(s)
            out = {"status": s["status"], "reason": str(s.get("reason"))[:240], "llm": (s.get("llm") or {}).get("level") or s.get("llm"),
                   "final_candidate": bool(s.get("final_file")), "validation": s.get("validation")}
            if d is not None:
                out["decision_core_hash"] = decision_core_hash(d)
                out["same_decisions_as_template"] = out["decision_core_hash"] == base_hash
            return out
        except Exception as ex:  # noqa: BLE001
            return {"status": "EXCEPTION", "reason": f"{type(ex).__name__}: {ex}", "trace": traceback.format_exc()[-600:]}

    res["faults"]["1_claude_unavailable"] = fault("claude_unavailable", provider=claude_provider("unavailable"),
                                                  llm_config="config/llm_claude_cli.yaml")
    res["faults"]["2_claude_timeout"] = fault("claude_timeout", provider=claude_provider("timeout"),
                                              llm_config="config/llm_claude_cli.yaml")
    res["faults"]["3_stale_market_data"] = fault("stale_market", store=_stale_store(store, T))
    res["faults"]["4_missing_institutional"] = fault("missing_institutional", data_faults={"institutional"})
    res["faults"]["5_missing_etf_holdings"] = fault("missing_etf", data_faults={"etf"})
    res["faults"].update(datapack_faults(T))
    res["faults"]["8_duplicate_invocation"] = duplicate_invocation()
    res["faults"]["9_invalid_dplan"] = invalid_dplan(d_tpl)
    res["faults"]["10_log_write_error"] = log_write_error(T, store)
    (OUT / "rehearsal_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str)[:12000])
    return 0


class _StaleStore:
    """Store view whose newest price day is removed -> T-1 prices look stale (read-only wrapper)."""
    def __init__(self, store, drop: str):
        self._s, self._drop = store, drop

    def __getattr__(self, k):
        return getattr(self._s, k)

    def dates(self, table):
        return [d for d in self._s.dates(table) if d != self._drop]

    def load(self, table, *a, **k):
        df = self._s.load(table, *a, **k)
        return df[df["date"] != self._drop] if "date" in getattr(df, "columns", []) else df


def _stale_store(store, T):
    from agent.ops.datapack import previous_trading_day
    return _StaleStore(store, previous_trading_day(T))


def datapack_faults(T: str) -> dict:
    """COMPETITION gate with malformed / stale DataPacks in an isolated folder (T = day 2+ so a DataPack is required)."""
    from agent.ops.datapack import datapack_gate
    from agent.ops.datapack_downloader import ManualFileProvider
    out = {}
    ops = iso_ops("fault_datapack")
    d = Path(ops["paths"]["official_datapack_dir"])
    d.mkdir(parents=True, exist_ok=True)
    day2 = "2026-10-28"
    (d / "malformed.json").write_text("{not json", encoding="utf-8")
    g = datapack_gate(day2, "TEAM_TEST", provider=ManualFileProvider(ops_cfg=ops), ops_cfg=ops)
    out["6_malformed_datapack"] = {k: g[k] for k in ("status", "reason", "file")} | {"problems": g["problems"][:2]}
    for f in d.glob("*.json"):
        f.unlink()
    ex = ROOT / "tests" / "fixtures" / "datapack"
    sample = next((p for p in ex.glob("*official*example*.json")), None) or next((p for p in ex.glob("*example*.json")), None)
    if sample:
        shutil.copy(sample, d / sample.name)
        g = datapack_gate(day2, "TEAM_TEST", provider=ManualFileProvider(ops_cfg=ops), ops_cfg=ops)
        out["7_stale_datapack"] = {k: g[k] for k in ("status", "reason", "file", "settlement_date")} | {"problems": g["problems"][:2],
                                   "note": f"official example file ({sample.name}) used as an out-of-date DataPack for T={day2}"}
    else:
        out["7_stale_datapack"] = {"status": "NOT_RUN", "reason": "no example DataPack found; covered by tests/ops/test_datapack_integration.py"}
    for f in d.glob("*.json"):
        f.unlink()
    g = datapack_gate(day2, "TEAM_TEST", provider=ManualFileProvider(ops_cfg=ops), ops_cfg=ops)
    out["6b_missing_datapack"] = {k: g[k] for k in ("status", "reason")}
    return out


def duplicate_invocation() -> dict:
    """Second scheduled invocation for an already-PASSed date is skipped (pure scheduler logic)."""
    from datetime import datetime
    from agent.ops.common import TPE
    from agent.ops.scheduled_run import already_passed, plan
    now = datetime(2026, 10, 18, 19, 45, tzinfo=TPE)
    p = plan(now, set())
    hist = [{"scheduled_date": p["scheduled_date"], "status": "PASS"}]
    return {"first_plan": p["action"], "second_invocation_already_passed": already_passed(p["scheduled_date"], hist),
            "result": "SKIPPED (SKIP_ALREADY_PASSED)" if already_passed(p["scheduled_date"], hist) else "WOULD_RUN_AGAIN",
            "task_scheduler": "MultipleInstances=IgnoreNew (concurrent trigger ignored by Windows)"}


def invalid_dplan(doc: dict | None) -> dict:
    """A corrupted D-Plan must fail the competition validator (never silently packaged)."""
    if not doc:
        return {"status": "NOT_RUN"}
    import jsonschema
    from agent.config import load_official_rules
    schema = json.loads(load_official_rules().schema_path.read_text(encoding="utf-8"))
    bad = copy.deepcopy(doc)
    bad["schema_version"] = "5.0"
    if bad.get("decisions"):
        bad["decisions"][0]["target_weight"] = 1.7
    if bad.get("no_trade_decisions"):
        bad["no_trade_decisions"][0]["ticker"] = "ABCDE"
    bad["orders"] = bad.get("orders", []) + [{"ticker": "9999", "side": "BUY", "shares": -5}]
    errs = [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(bad)]
    out = {"schema_errors_found": len(errs), "examples": errs[:3]}
    try:
        from agent.engine.validator import ValidationContext, validate_dplan  # noqa: F401
        out["note"] = "competition validator also re-checks weights / tickers / orders before packaging"
    except Exception:  # noqa: BLE001
        pass
    out["status"] = "REJECTED" if errs else "NOT_REJECTED"
    return out


def log_write_error(T: str, store) -> dict:
    """ops log dir is a FILE (cannot create the day folder) -> the run must fail loudly, not write a D-Plan elsewhere."""
    ops = iso_ops("fault_logwrite")
    p = Path(ops["paths"]["ops_logs_dir"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not a directory", encoding="utf-8")
    try:
        s, _ = run_day(T, "fault_logwrite", store=store, ops=ops)
        return {"status": s["status"], "reason": str(s.get("reason"))[:200], "final_candidate": bool(s.get("final_file"))}
    except Exception as ex:  # noqa: BLE001
        return {"status": "EXCEPTION_RAISED (loud failure, no D-Plan)", "reason": f"{type(ex).__name__}: {str(ex)[:160]}",
                "submissions_written": any((Path(ops["paths"]["submissions_dir"])).rglob("*.json"))
                if Path(ops["paths"]["submissions_dir"]).exists() else False}


if __name__ == "__main__":
    raise SystemExit(main())
