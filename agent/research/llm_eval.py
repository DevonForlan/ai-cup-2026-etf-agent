"""Phase 5A evaluation of the LLM layer (does NOT affect decisions).

For each trading day of the given windows:
  * event extraction over all PIT-visible announcements (normal and blind prompts)
  * market narrative + thesis writing for Quant v1's actual D-Plan of that day
Measures schema pass rate, hallucination drops (by reason), narrative review failures, latency
p50/p95, tokens/day and calls/day. Writes reports/round04_llm_eval.json.

  python agent\\research\\llm_eval.py --provider mock --windows W5,W1 --days 10
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.data.pit import PITView  # noqa: E402
from agent.engine.rules import load_rulebook  # noqa: E402
from agent.llm.client import LLMClient, load_llm_config, make_provider  # noqa: E402
from agent.llm.logging import LLMCallLogger  # noqa: E402
from agent.research.event_extractor import EventExtractor, revenue_facts, visible_documents  # noqa: E402
from agent.sim.calendar import TradingCalendar  # noqa: E402


def pct(xs, q):
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="mock")
    ap.add_argument("--windows", default="W5,W1")
    ap.add_argument("--days", type=int, default=10, help="days per window")
    a = ap.parse_args(argv)
    from agent.pipeline import cached_features, run_day
    from agent.config import load_yaml
    from agent.sim.models import Settlement
    rb = load_rulebook()
    st = HistoryStore()
    cal = TradingCalendar(st.dates("daily_prices"))
    wins = json.loads((ROOT / "reports" / "windows.json").read_text(encoding="utf-8"))
    cfg_q = load_yaml("config/strategy_quant_v1.yaml")
    out = {"provider": a.provider, "windows": {}, "note": "mock = deterministic keyword stand-in, not an LLM"}
    tot = {"days": 0, "calls": 0, "tokens": 0, "lat": [], "day_tokens": [], "day_calls": []}
    for wid in a.windows.split(","):
        days = [d for d in cal.days if d >= wins[wid]["start"]][: a.days]
        res = {}
        for blind in (False, True):
            lc = load_llm_config()
            lc.update({"provider": a.provider, "blind_mode": blind})
            stats_acc, n_ev = {}, 0
            lat, toks = [], []
            for d in days:
                cl = LLMClient(lc, provider=make_provider(lc), logger=LLMCallLogger(ROOT / "logs" / "llm_eval", d))
                fs = cached_features(st, f"{d}T07:00:00+08:00", d, sorted(rb.universe))[0]
                docs = visible_documents(PITView(st, f"{d}T07:00:00+08:00"), d, set(rb.universe), 1, 400)
                ex = EventExtractor(cl, rb.universe)
                evs = ex.extract(docs, revenue_facts(fs.features, sorted({x.ticker for x in docs})))
                n_ev += len(evs)
                for k, v in ex.stats.__dict__.items():
                    stats_acc[k] = stats_acc.get(k, 0) + v
                sm = cl.logger.summary()
                lat += [r.get("latency_sec", 0) for r in cl.logger.records if r["status"] == "ok"]
                toks.append(sm["input_tokens"] + sm["output_tokens"])
            raw = stats_acc.get("events_raw", 0)
            hall = sum(stats_acc.get(k, 0) for k in ("dropped_ticker", "dropped_source", "dropped_number",
                                                     "dropped_fact_ref", "dropped_injection"))
            res["blind" if blind else "normal"] = {
                "days": len(days), "documents": stats_acc.get("documents", 0), "calls": stats_acc.get("calls", 0),
                "schema_failures": stats_acc.get("schema_failures", 0),
                "schema_failure_rate": stats_acc.get("schema_failures", 0) / max(1, stats_acc.get("calls", 0)),
                "events_raw": raw, "events_kept": n_ev, "drops": {k: stats_acc.get(k, 0) for k in
                    ("dropped_ticker", "dropped_source", "dropped_number", "dropped_fact_ref", "dropped_injection")},
                "hallucination_rate": hall / max(1, raw), "latency_p50": pct(lat, 0.5), "latency_p95": pct(lat, 0.95),
                "tokens_per_day": statistics.mean(toks) if toks else 0}
        # narrative over the same days (Quant v1 actual path, LLM text only)
        lc = load_llm_config()
        lc.update({"provider": a.provider})
        lc["narrative"]["mode"] = "llm"
        prev = Settlement.initial(cal.prev(days[0]), rb.rules.initial_cash)
        narr = {"days": 0, "llm_used_days": 0, "validation_ok": 0, "calls": 0, "failed": 0, "tokens": [], "lat": [],
                "run_sec": []}
        from agent.pipeline import day_market, update_state_after_settlement
        from agent.sim.settle import settle
        for d in days:
            t0 = time.perf_counter()
            r = run_day(d, st, prev, rb, cfg_q, team_id="TEAM_EVAL", out_dir=ROOT / "logs" / "llm_eval" / "out",
                        log_dir=ROOT / "logs" / "llm_eval" / "runs", calendar=cal, light=True,
                        llm={"cfg": lc, "provider": make_provider(lc), "log_root": ROOT / "logs" / "llm_eval"})
            narr["run_sec"].append(time.perf_counter() - t0)
            s = settle(prev, r.doc["orders"] if r.validation.ok else None, day_market(st, d), rb)
            s.agent_state = update_state_after_settlement(r.agent_state, prev.holdings, s.holdings, d)
            prev = s
            narr["days"] += 1
            narr["llm_used_days"] += int(r.narrative_used_llm)
            narr["validation_ok"] += int(r.validation.ok)
            narr["calls"] += r.llm_summary.get("calls", 0)
            narr["failed"] += r.llm_summary.get("failed", 0)
            narr["tokens"].append(r.llm_summary.get("input_tokens", 0) + r.llm_summary.get("output_tokens", 0))
            narr["lat"].append(r.llm_summary.get("latency_p95", 0))
        res["narrative"] = {"days": narr["days"], "llm_used_days": narr["llm_used_days"],
                            "validation_pass_rate": narr["validation_ok"] / max(1, narr["days"]),
                            "calls": narr["calls"], "failed": narr["failed"],
                            "tokens_per_day": statistics.mean(narr["tokens"]) if narr["tokens"] else 0,
                            "run_sec_p50": pct(narr["run_sec"], 0.5), "run_sec_p95": pct(narr["run_sec"], 0.95)}
        out["windows"][wid] = res
        print(wid, json.dumps(res, ensure_ascii=False))
    p = ROOT / "reports" / "round04_llm_eval.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", p)


if __name__ == "__main__":
    main()
