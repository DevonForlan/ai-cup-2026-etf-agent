"""3-day / 15-day W5 replay: Template vs Claude Code CLI narrative through the real pipeline (run_day x2 per day,
agent/ops/llm_review.py invariance + A–I checks). Then: ReplayProvider re-runs from the logged CLI responses and
must reproduce the narrative, the D-Plan core and the decision fingerprint exactly (no CLI call).

  ..\\..\\.venv\\Scripts\\python.exe narrative_replay.py --days 3
  ..\\..\\.venv\\Scripts\\python.exe narrative_replay.py --days 15
Outputs: reports/round06b_cli_replay/<n>d/, reports/human_review_cli/YYYY-MM-DD_review.md
"""
import argparse
import json
import sys
import time
from pathlib import Path

from _common import ROOT, write
from agent.ops.llm_review import run_review
from agent.llm.providers.claude_cli import ClaudeCodeCLIProvider
from agent.llm.client import load_llm_config


def replay_check(out, days: int) -> dict:
    """Re-run every day with ReplayProvider over the logged CLI responses (no CLI call) and compare."""
    import copy
    from agent.config import load_strategy
    from agent.data.loaders import HistoryStore
    from agent.engine.rules import load_rulebook
    from agent.llm.replay import ReplayProvider
    from agent.ops.fingerprint import decision_core_hash, narrative_text
    from agent.pipeline import llm_settings, run_day
    from agent.sim.calendar import TradingCalendar
    from agent.sim.models import Settlement
    import tempfile
    store, rb = HistoryStore(), load_rulebook()
    strat = load_strategy("config/strategy_quant_v1.yaml")
    cal = TradingCalendar(store.dates("daily_prices"))
    run = ROOT / "sim_runs" / "round06_baseline_quant_v1"
    rp = ReplayProvider([out / "llm_logs"])
    rows = []
    for f in sorted((out / "docs").glob("*_llm.json"))[:days]:
        d = f.name[:10]
        orig = json.loads(f.read_text(encoding="utf-8"))
        prev_p = run / "settlement" / f"{cal.prev(d)}.json"
        prev = Settlement.load(prev_p) if prev_p.exists() else Settlement.initial(cal.prev(d), rb.rules.initial_cash)
        llm = llm_settings(strat, "llm", None, "config/llm_claude_cli.yaml", provider_instance=rp,
                           log_root=Path(tempfile.mkdtemp()))
        r = run_day(d, store, copy.deepcopy(prev), rb, strat, team_id="TEAM_SIM", out_dir=Path(tempfile.mkdtemp()),
                    log_dir=None, calendar=cal, light=True, llm=llm)
        rows.append({"date": d, "narrative_identical": narrative_text(r.doc) == narrative_text(orig),
                     "decision_core_identical": decision_core_hash(r.doc) == decision_core_hash(orig),
                     "dplan_identical_except_metadata": {k: v for k, v in r.doc.items() if k != "agent_metadata"}
                     == {k: v for k, v in orig.items() if k != "agent_metadata"},
                     "validation_ok": r.validation.ok, "used_llm_text": r.narrative_used_llm})
    return {"days": len(rows), "all_identical": all(x["narrative_identical"] and x["decision_core_identical"]
                                                   and x["dplan_identical_except_metadata"] for x in rows), "rows": rows}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    a = ap.parse_args()
    cfg = dict(load_llm_config("config/llm_claude_cli.yaml"), enabled=True)
    prov = ClaudeCodeCLIProvider(None, cfg)
    out = ROOT / "reports" / "round06b_cli_replay" / f"{a.days}d"
    t0 = time.time()
    s = run_review(days=a.days, llm_config="config/llm_claude_cli.yaml", provider_instance=prov,
                   replay_run="sim_runs/round06_baseline_quant_v1", out_dir=out,
                   human_review_dir=ROOT / "reports" / "human_review_cli", log_root=out / "llm_logs", save_docs=True)
    s["wall_sec"] = round(time.time() - t0, 1)
    s["replay_check"] = replay_check(out, a.days)
    write(f"narrative_replay_{a.days}d", s)
    print(json.dumps({k: s.get(k) for k in ("days", "invariance_failures", "order_invariance_rate", "validation_rate",
                                             "numeric_grounding_rate", "fallback_rate", "schema_failure_rate",
                                             "latency_max", "tokens_per_day", "checks_pass_rate", "wall_sec")} | {"replay_all_identical": s["replay_check"]["all_identical"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
