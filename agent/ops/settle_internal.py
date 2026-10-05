"""Evening internal settlement for trade date T (after T's close data is available, ~15:00+).

previous internal settlement (T-1) + the FINAL D-Plan of T + T VWAP/close (+ corporate actions)
  -> data/settlement/YYYYMMDD_internal.json   (agent_state taken from the FINAL candidate)

  python agent\\ops\\settle_internal.py --date 2026-10-27 [--refresh]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.data.loaders import HistoryStore  # noqa: E402
from agent.engine.rules import load_rulebook  # noqa: E402
from agent.ops.common import load_ops_config, ops_path, ymd  # noqa: E402
from agent.ops.settlement import load_internal, save_internal  # noqa: E402
from agent.pipeline import day_market, update_state_after_settlement  # noqa: E402
from agent.sim.calendar import TradingCalendar  # noqa: E402
from agent.sim.models import Settlement  # noqa: E402
from agent.sim.settle import settle  # noqa: E402


def final_candidate(trade_date: str, ops_cfg: dict) -> tuple[dict | None, dict, Path | None]:
    day = ops_path(ops_cfg, "submissions_dir") / ymd(trade_date)
    hist = day / "final_history.jsonl"
    if not hist.exists():
        return None, {}, None
    rec = json.loads(hist.read_text(encoding="utf-8").strip().splitlines()[-1])
    pkg = day / "candidates" / rec["run_id"]
    doc = json.loads((pkg / rec["file"]).read_text(encoding="utf-8"))
    st = pkg / "agent_state.json"
    return doc, (json.loads(st.read_text(encoding="utf-8")) if st.exists() else {}), pkg


def settle_day(trade_date: str, *, store: HistoryStore | None = None, ops_cfg: dict | None = None,
               prev: Settlement | None = None, initial_cash=None) -> Settlement:
    ops_cfg = ops_cfg or load_ops_config()
    store = store or HistoryStore()
    rb = load_rulebook()
    cal = TradingCalendar(store.dates("daily_prices"))
    if trade_date not in cal.days:
        raise RuntimeError(f"no T-day market data for {trade_date} yet (VWAP/close needed)")
    pd_ = cal.prev(trade_date)
    if prev is None:
        prev = load_internal(pd_, ops_cfg)
    if prev is None:
        if initial_cash is None:
            raise RuntimeError(f"no internal settlement for {pd_}; pass --initial for day 1")
        prev = Settlement.initial(pd_, initial_cash)
    doc, state, _ = final_candidate(trade_date, ops_cfg)
    orders = doc["orders"] if doc else None           # no FINAL -> treated as not submitted (warning)
    s = settle(prev, orders, day_market(store, trade_date), rb)
    s.agent_state = update_state_after_settlement(state or prev.agent_state, prev.holdings, s.holdings, trade_date)
    save_internal(s, ops_cfg)
    return s


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--initial", action="store_true", help="day 1: start from initial cash")
    ap.add_argument("--refresh", action="store_true", help="fetch T prices first")
    a = ap.parse_args(argv)
    if a.refresh:
        from agent.ops.refresh_daily import refresh
        from datetime import date, timedelta
        nxt = (date.fromisoformat(a.date) + timedelta(days=1)).isoformat()
        refresh(nxt, only={"twse_prices", "tpex_prices"})
    rb = load_rulebook()
    s = settle_day(a.date, initial_cash=rb.rules.initial_cash if a.initial else None)
    print(f"INTERNAL SETTLEMENT {a.date}: NAV {float(s.nav):,.0f}  cash {float(s.cash / s.nav):.2%}  "
          f"holdings {len(s.holdings)}  warnings {[w['rule'] for w in s.warnings]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
