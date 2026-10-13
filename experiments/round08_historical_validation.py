"""Round 08-P: historical validation on REAL stored market data (3 consecutive trading days).

For each day T: T-1 evening prediction (competition_day, historical mode, template narrative — deterministic)
-> T evaluation (agent.ops.daily_evaluation.evaluate) -> paper ledger -> next day's prediction starts from it.
Everything is written to an isolated directory (runtime/round08_hv/); real submissions/ and the real
paper ledger are untouched. Checks: date alignment, order alignment, settlement reproducibility, NAV
recomputation, return attribution, report presence, and NAV equality with the independent run_sim replay.

    .venv\\Scripts\\python.exe experiments\\round08_historical_validation.py --days 2026-10-07,2026-10-08,2026-10-12
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.competition_day import run_competition_day  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.engine.rules import load_rulebook  # noqa: E402
from agent.ops.common import Clock, load_ops_config  # noqa: E402
from agent.ops.daily_evaluation import Paths, evaluate  # noqa: E402
from agent.pipeline import day_market  # noqa: E402
from agent.sim.calendar import TradingCalendar  # noqa: E402
from agent.sim.models import Settlement  # noqa: E402
from agent.sim.settle import settle  # noqa: E402

OUT = ROOT / "runtime" / "round08_hv"
CLEAN_GIT = {"sha": "hv000", "branch": "master", "dirty_paths": []}


def iso_ops() -> dict:
    c = copy.deepcopy(load_ops_config())
    for k, v in c["paths"].items():
        c["paths"][k] = str(OUT / "ops" / Path(v).name)
    return c


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="2026-10-07,2026-10-08,2026-10-12")
    a = ap.parse_args()
    days = a.days.split(",")
    shutil.rmtree(OUT, ignore_errors=True)
    ops = iso_ops()
    paths = Paths(ledger=OUT / "ledger", reports=OUT / "reports", logs=OUT / "logs")
    store = HistoryStore()
    cal = TradingCalendar(store.dates("daily_prices"))
    rb = load_rulebook()
    results, checks = [], {}
    for i, t in enumerate(days):
        prev = cal.prev(t)
        s = run_competition_day(t, "TEAM_TEST", "historical", store=store, ops_cfg=ops, clock=Clock(f"{prev}T20:00:00+08:00"),
                                skip_refresh=True, initial=(i == 0), replay_run=None if i == 0 else str(paths.ledger),
                                git=CLEAN_GIT, archive_readonly=False, write_report=False)
        assert s["status"] == "HISTORICAL_OK", (t, s["status"], s.get("reason"))
        r = evaluate(t, ops_cfg=ops, store=store, paths=paths)
        doc = json.loads(Path(r["prediction_file"]).read_text(encoding="utf-8")) if Path(r["prediction_file"]).is_absolute() \
            else json.loads((ROOT / r["prediction_file"]).read_text(encoding="utf-8"))
        led = Settlement.load(paths.settlement(t))
        prevs = Settlement.load(paths.settlement(prev)) if paths.settlement(prev).exists() else Settlement.initial(prev, rb.rules.initial_cash)
        again = settle(prevs, doc["orders"], day_market(store, t), rb)
        filled = {(x["ticker"], x["side"], x["shares"]) for x in led.executions if x.get("vwap")}
        ordered = {(o["ticker"], o["side"], o["shares"]) for o in doc["orders"]}
        c = {"status": r["status"], "date_aligned": doc["trade_date"] == t == r["evaluation_date"] and r["previous_date"] == prev,
             "start_source": r["start_source"], "orders_aligned": filled <= ordered and len(filled) == len(ordered),
             "settlement_reproducible": again.nav == led.nav and again.holdings == led.holdings and again.cash == led.cash,
             "nav_reconciliation": r["settlement"], "attribution": r["return_attribution_check"],
             "report": Path(r["report_file"]).exists(), "nav": r["nav"], "daily_return": r["daily_return"],
             "orders": len(doc["orders"]), "holdings": r["holding_count"]}
        checks[t] = c
        results.append(r)
        print(t, json.dumps(c, ensure_ascii=False))
    # independent cross-check: run_sim over the same days from initial cash
    rid = "round08_hv_sim"
    subprocess.run([sys.executable, str(ROOT / "agent" / "run_sim.py"), "--start", days[0], "--days", str(len(days)),
                    "--config", "config/strategy_quant_v1.yaml", "--run-id", rid], cwd=ROOT, capture_output=True)
    sim = json.loads((ROOT / "sim_runs" / rid / "summary.json").read_text(encoding="utf-8"))
    sim_days = [json.loads(p.read_text(encoding="utf-8"))["nav"] for p in sorted((ROOT / "sim_runs" / rid / "settlement").glob("*.json"))]
    out = {"days": days, "checks": checks, "sim_final_nav": sim["final_nav"], "paper_final_nav": results[-1]["nav"],
           "sim_daily_navs": sim_days[-len(days):],
           "nav_equal_to_run_sim": abs(float(sim["final_nav"]) - float(results[-1]["nav"])) < 0.01}
    out["ALL_PASS"] = out["nav_equal_to_run_sim"] and all(
        v["status"] == "PASS" and v["date_aligned"] and v["orders_aligned"] and v["settlement_reproducible"]
        and v["nav_reconciliation"] == "PASS" and v["attribution"] == "PASS" and v["report"] for v in checks.values())
    (ROOT / "reports" / "round08_historical_validation.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                                         encoding="utf-8")
    print("SIM", sim["final_nav"], "PAPER", results[-1]["nav"], "ALL_PASS", out["ALL_PASS"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
