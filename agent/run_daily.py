"""Daily run: produce today's D-Plan.

  python agent\\run_daily.py --date 2026-10-02 --mode replay --team-id TEAM_TEST
  python agent\\run_daily.py --date 2026-10-02 --mode replay --prev-settlement sim_runs\\x\\settlement\\2026-10-01.json

Without --prev-settlement the portfolio starts from initial cash (day-1 situation).
Live mode fetches T-1 data first (TWSE/TPEx) and uses wall-clock time for metadata.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.config import ROOT, load_strategy  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.data.providers import LiveProvider  # noqa: E402
from agent.engine.rules import load_rulebook  # noqa: E402
from agent.pipeline import run_day  # noqa: E402
from agent.sim.calendar import TradingCalendar  # noqa: E402
from agent.sim.models import Settlement  # noqa: E402


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Generate one day's D-Plan")
    ap.add_argument("--date", required=True, help="trade date YYYY-MM-DD")
    ap.add_argument("--mode", choices=["replay", "live"], default="replay")
    ap.add_argument("--team-id", default=None)
    ap.add_argument("--config", default="config/strategy.yaml")
    ap.add_argument("--history", default=str(ROOT / "data" / "history"))
    ap.add_argument("--prev-settlement", default=None)
    ap.add_argument("--out", default=str(ROOT / "out"))
    ap.add_argument("--method", default=None, help="B0_score_tiered|B1_score_equal|B2_momentum|B3_institutional")
    ap.add_argument("--fixture", action="store_true", help="history is a fixture/synthetic store")
    a = ap.parse_args(argv)

    cfg = load_strategy(a.config)
    rb = load_rulebook()
    team = a.team_id or cfg.get("team_id", "TEAM_TEST")
    store = HistoryStore(a.history)
    cal = None
    if a.mode == "live":
        cal = TradingCalendar.weekdays("2025-01-01", a.date)
        lp = LiveProvider(store)
        prev_d = cal.prev(a.date)
        lp.refresh(prev_d)
        for e in lp.errors:
            print("[live fetch error]", e)
    prev = Settlement.load(a.prev_settlement) if a.prev_settlement else Settlement.initial("initial", rb.rules.initial_cash)
    r = run_day(a.date, store, prev, rb, cfg, team_id=team, mode=a.mode, out_dir=Path(a.out), method=a.method,
                store_is_fixture=a.fixture, calendar=cal)
    v = r.validation
    print(f"D-Plan: {r.dplan_path}")
    print(f"fallback={r.fallback}  decisions={len(r.doc['decisions'])}  no_trade={len(r.doc['no_trade_decisions'])}"
          f"  orders={len(r.doc['orders'])}")
    print(f"validation: {'PASS' if v.ok else 'FAIL'} {v.summary()}")
    for c in v.checks:
        if c.status.value in ("FAIL", "WARNING", "UNKNOWN"):
            print(f"  [{c.status.value}] {c.rule_id}: {c.message}")
    for n in r.notes:
        print("  note:", n)
    return 0 if v.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
