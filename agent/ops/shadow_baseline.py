"""Issue #48 - untouched Frozen Quant v1 SHADOW baseline for a tactical day, and the three-way post-close comparison.

    python -m agent.ops.shadow_baseline generate --date 2026-11-09 [--root PRODUCTION_ROOT] [--publish]
    python -m agent.ops.shadow_baseline compare  --date 2026-11-09 [--root PRODUCTION_ROOT] [--publish]

SHADOW_BASELINE_NOT_FOR_SUBMISSION: the shadow D-Plan is written ONLY under logs/shadow/<yyyymmdd>/ (never under
submissions/, so no scheduled task, catch-up or retry can find or upload it) and this module imports nothing from the
submission / portal packages. The tactical override is never activated here: Frozen Quant v1 (agent.pipeline.run_day) runs
alone from the SAME settlement state, data store and decision as-of as the submitted run. Nothing frozen is touched.

compare: after the official close, the same deterministic simulator (agent.sim.settle.settle, as the 17:00 evaluation) settles
three order sets from the same opening state: BASELINE (shadow artifact frozen before the outcome), TACTICAL_V1 (superseded
FINAL, archived) and TACTICAL_V2 (confirmed FINAL). The baseline is never regenerated with later information.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

from agent.config import ROOT, D, load_strategy
from agent.ops.common import ymd

MARK = "SHADOW_BASELINE_NOT_FOR_SUBMISSION"
FROZEN_FP = "f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _tech() -> set[str]:
    import yaml
    c = yaml.safe_load((ROOT / "config" / "tactical_override_v2.yaml").read_text(encoding="utf-8"))
    return {str(t) for t in c["reduce_tickers"]}


def _jload(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _paths(root: Path, td: str):
    d = root / "logs" / "shadow" / ymd(td)
    return d, root / "submissions" / ymd(td)


def _summ(h: dict, cash, nav, closes, tech: set[str], extra: dict | None = None) -> dict:
    w = {t: float(D(s) * D(closes[t]) / D(nav)) for t, s in h.items() if int(s) > 0}
    out = {"holdings": {t: int(s) for t, s in sorted(h.items()) if int(s) > 0}, "weights": dict(sorted(w.items())),
           "cash_weight": float(D(cash) / D(nav)), "tech_weight": sum(v for t, v in w.items() if t in tech),
           "n_holdings": len(w)}
    out.update(extra or {})
    return out


def generate(td: str, root: Path | None = None) -> dict:
    from agent.data.loaders import HistoryStore
    from agent.engine.rules import load_rulebook
    from agent.pipeline import run_day
    from agent.sim.calendar import TradingCalendar
    from agent.sim.models import Settlement
    root = Path(root or ROOT)
    out, subs = _paths(root, td)
    out.mkdir(parents=True, exist_ok=True)
    fp = _sha((ROOT / "config" / "strategy_quant_v1.yaml").read_bytes())
    if fp != FROZEN_FP:
        raise SystemExit(f"Frozen Quant v1 fingerprint mismatch {fp} - STOP")
    summary = _jload(root / "logs" / "ops" / ymd(td) / "competition_day_summary.json")
    s = summary["start"]
    rb, cfg, store = load_rulebook(), load_strategy("config/strategy_quant_v1.yaml"), HistoryStore()
    cal = TradingCalendar(store.dates("daily_prices") + [td])
    start = Settlement(s["date"], {t: int(n) for t, n in s["holdings"].items()}, D(s["cash"]), D(s["nav"]),
                       initial_nav=rb.rules.initial_cash)
    as_of = summary["started_at"]
    r = run_day(td, store, start, rb, cfg, team_id=summary["team_id"], mode="replay", out_dir=out / "dplan", log_dir=out / "log",
                calendar=cal, llm=None, as_of_override=as_of, data_faults=set(), store_is_fixture=False)
    tp = r.result
    dp = Path(r.dplan_path)
    sha = _sha(dp.read_bytes())
    closes = r.closes_prev
    tech = _tech()
    acts = {"orders": [{"ticker": o.ticker, "side": o.side, "shares": int(o.shares)} for o in tp.orders],
            "validation": r.validation.summary(), "validation_ok": bool(r.validation.ok), "fallback": bool(r.fallback),
            "active_share_min": (None if getattr(tp.active_share, "minimum_active_share", None) is None
                                 else float(tp.active_share.minimum_active_share))}
    base = _summ(tp.est_holdings, tp.est_cash, tp.est_nav, closes, tech, acts)
    # same-snapshot evidence: the settlement hash of the opening state and the data store dates of this run
    rec = {"status": MARK, "trade_date": td, "frozen_quant_v1_fingerprint": fp, "tactical_override": "NOT_ACTIVATED",
           "baseline_shadow_sha256": sha, "baseline_file": str(dp.relative_to(root)) if dp.is_relative_to(root) else str(dp),
           "as_of": as_of, "opening_settlement": {"date": s["date"], "settlement_hash": s.get("settlement_hash"),
                                                  "nav": s["nav"], "cash": s["cash"]},
           "submitted_run": {"run_id": summary.get("run_id"), "sha256": summary.get("sha256"),
                             "decision_fingerprint": summary.get("decision_fingerprint")},
           "portfolio": base}
    (out / MARK).write_text("This directory holds an untouched Frozen Quant v1 SHADOW baseline. It is never submitted.\n",
                            encoding="utf-8")
    (out / "BASELINE_SHADOW.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return rec


def _final_orders(p: Path) -> list[dict]:
    return [{"ticker": o["ticker"], "side": o["side"], "shares": int(o["shares"])} for o in _jload(p)["orders"]]


def _orders_after(h0: dict, orders: list[dict]) -> dict:
    h = dict(h0)
    for o in orders:
        h[o["ticker"]] = h.get(o["ticker"], 0) + (o["shares"] if o["side"] == "BUY" else -o["shares"])
    return {t: n for t, n in h.items() if n > 0}


def compare(td: str, root: Path | None = None) -> dict:
    from agent.data.loaders import HistoryStore
    from agent.engine.rules import load_rulebook
    from agent.pipeline import day_market
    from agent.sim.models import Settlement
    from agent.sim.settle import settle
    root = Path(root or ROOT)
    out, subs = _paths(root, td)
    base = _jload(out / "BASELINE_SHADOW.json")
    summary = _jload(root / "logs" / "ops" / ymd(td) / "competition_day_summary.json")
    s = summary["start"]
    rb, store = load_rulebook(), HistoryStore()
    if td not in set(store.dates("daily_prices")):
        return {"status": "MARKET_DATA_NOT_AVAILABLE", "trade_date": td}
    mkt = day_market(store, td)
    start = Settlement(s["date"], {t: int(n) for t, n in s["holdings"].items()}, D(s["cash"]), D(s["nav"]),
                       initial_nav=rb.rules.initial_cash)
    sets = {"BASELINE": base["portfolio"]["orders"], "TACTICAL_V2": _final_orders(subs / "FINAL" / f"D-Plan_{summary['team_id']}_{td}.json")}
    sup = sorted((subs / "superseded").glob("*/FINAL/D-Plan_*.json")) if (subs / "superseded").is_dir() else []
    if sup:
        sets["TACTICAL_V1"] = _final_orders(sup[0])
    tech = _tech()
    res: dict = {}
    for name, orders in sets.items():
        st = settle(start, orders, mkt, rb)
        flows: dict[str, Decimal] = {}
        for x in st.executions:
            if x.get("vwap"):
                flows[x["ticker"]] = flows.get(x["ticker"], D(0)) + (1 if x["side"] == "BUY" else -1) * D(x["shares"]) * D(x["vwap"])
        pcl = start.closes or {}
        contrib = {}
        for t in set(start.holdings) | set(st.holdings):
            end_v = D(st.holdings.get(t, 0)) * mkt.close.get(t, D(0))
            start_v = D(start.holdings.get(t, 0)) * D((pcl.get(t) or mkt.close.get(t, 0)))
            contrib[t] = float((end_v - start_v - flows.get(t, D(0))) / start.nav)
        res[name] = {"nav": float(st.nav), "return_pct": float(st.nav / start.nav - 1) * 100, "fees": float(st.fees),
                     "tax": float(st.tax), "cash_weight": float(st.cash / st.nav), "n_holdings": len(st.holdings),
                     "tech_weight": float(sum((D(n) * mkt.close[t] for t, n in st.holdings.items() if t in tech and t in mkt.close), D(0)) / st.nav),
                     "executions_void": bool(st.trades_void), "compliance_warnings": [w.get("rule") for w in st.warnings],
                     "contribution": contrib}
    b = res["BASELINE"]
    for k, v in res.items():
        v["minus_baseline_twd"] = v["nav"] - b["nav"]
        v["minus_baseline_pp"] = v["return_pct"] - b["return_pct"]
    top = lambda c, rev: sorted(c.items(), key=lambda kv: kv[1], reverse=rev)[:5]  # noqa: E731
    t2 = res["TACTICAL_V2"]
    diff = {t: t2["contribution"].get(t, 0.0) - b["contribution"].get(t, 0.0) for t in set(t2["contribution"]) | set(b["contribution"])}
    verdict = ("INCONCLUSIVE" if abs(t2["minus_baseline_pp"]) < 0.05 else "HELPED" if t2["minus_baseline_pp"] > 0 else "HURT")
    rec = {"status": "COMPARED", "trade_date": td, "label": "COMPETITION_DAY_ESTIMATE (simulator, not official settlement)",
           "baseline_shadow_sha256": base["baseline_shadow_sha256"], "frozen_quant_v1_fingerprint": FROZEN_FP,
           "opening_nav": s["nav"], "results": {k: {a: c for a, c in v.items() if a != "contribution"} for k, v in res.items()},
           "top_positive_v2_vs_baseline": top(diff, True), "top_negative_v2_vs_baseline": top(diff, False),
           "tech_names_contribution_diff": {t: round(diff[t], 6) for t in sorted(diff) if t in tech and abs(diff[t]) > 1e-6},
           "manual_intervention_result_v2": verdict}
    (out / "COMPARISON_POST_CLOSE.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return rec


def pre_comparison(td: str, root: Path | None = None) -> dict:
    """The pre-market comparison record of Issue #48 (shadow vs the submitted FINAL), no market outcome involved."""
    root = Path(root or ROOT)
    out, subs = _paths(root, td)
    base = _jload(out / "BASELINE_SHADOW.json")
    summary = _jload(root / "logs" / "ops" / ymd(td) / "competition_day_summary.json")
    fin = subs / "FINAL" / f"D-Plan_{summary['team_id']}_{td}.json"
    fsha = _sha(fin.read_bytes())
    tact = (summary.get("tactical_override") or {})
    bp = base["portfolio"]
    names_b, names_t = set(bp["holdings"]), set(tact.get("weights_after") or {})
    rec = {"TRADE_DATE": td, "TACTICAL_FINAL_SHA": fsha, "BASELINE_SHADOW_SHA": base["baseline_shadow_sha256"],
           "SAME_DATA_SNAPSHOT": "PASS" if base["as_of"] == summary.get("started_at") else "FAIL",
           "SAME_SETTLEMENT_BASE": ("PASS" if base["opening_settlement"]["settlement_hash"] == summary["start"].get("settlement_hash") else "FAIL"),
           "TACTICAL_VERSION": tact.get("version"), "FROZEN_QUANT_V1_FINGERPRINT": FROZEN_FP,
           "BASELINE_HOLDINGS": bp["holdings"], "BASELINE_WEIGHTS": bp["weights"], "BASELINE_ORDERS": bp["orders"],
           "TACTICAL_WEIGHTS": tact.get("weights_after"), "TACTICAL_ORDERS": _final_orders(fin),
           "DIFF_ADDED_NAMES": sorted(names_t - names_b), "DIFF_REMOVED_OR_REDUCED_NAMES": sorted(names_b - names_t),
           "TECH_WEIGHT_TACTICAL": tact.get("tech_weight_after"), "TECH_WEIGHT_BASELINE": bp["tech_weight"],
           "CASH_TACTICAL": tact.get("cash_weight_after"), "CASH_BASELINE": bp["cash_weight"],
           "ACTIVE_SHARE_TACTICAL": summary.get("active_share_min"), "ACTIVE_SHARE_BASELINE": bp["active_share_min"],
           "COMPLIANCE_TACTICAL": summary.get("validation_summary"), "COMPLIANCE_BASELINE": bp["validation"],
           "BASELINE_SUBMISSION_STATUS": MARK,
           "TACTICAL_SUBMISSION_STATUS": (_jload(subs / "submission_state.json").get("state"))}
    (out / "COMPARISON_PRE.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    return rec


def publish(td: str, root: Path | None = None) -> list[str]:
    """Copy the three records to the shared-state branch (downstream only; never raises)."""
    from agent.ops import shared_state_sync as S
    done = []
    try:
        root = S._root(root)
        out, _ = _paths(root, td)
        wt = S.ensure_worktree(root)
        dst = wt / "shared_state" / "shadow" / td
        dst.mkdir(parents=True, exist_ok=True)
        for n in ("BASELINE_SHADOW.json", "COMPARISON_PRE.json", "COMPARISON_POST_CLOSE.json"):
            if (out / n).exists():
                (dst / n).write_bytes((out / n).read_bytes())
                done.append(n)
        S._git(wt, "add", "-A", "shared_state/shadow")
        if S._git(wt, "diff", "--cached", "--quiet", check=False).returncode != 0:
            S._git(wt, "commit", "-q", "-m", f"shared-state: shadow baseline {td} ({', '.join(done)})\n\n"
                   "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>")
        for _ in range(S.PUSH_ATTEMPTS):
            if S._git(wt, "push", "-u", "origin", S.BRANCH, check=False).returncode == 0:
                break
            S._git(wt, "pull", "--rebase", "origin", S.BRANCH, check=False)
    except Exception as e:  # noqa: BLE001
        done.append(f"PUBLISH_PENDING {type(e).__name__}: {e}"[:200])
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("generate", "compare"))
    ap.add_argument("--date", required=True)
    ap.add_argument("--root", default=None)
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "generate":
        r = generate(a.date, a.root)
        r2 = pre_comparison(a.date, a.root)
        print(json.dumps({"baseline_shadow_sha256": r["baseline_shadow_sha256"], "status": r["status"], "pre": {
            k: r2[k] for k in ("SAME_DATA_SNAPSHOT", "SAME_SETTLEMENT_BASE", "TECH_WEIGHT_BASELINE", "TECH_WEIGHT_TACTICAL")}}, indent=1))
    else:
        r = compare(a.date, a.root)
        print(json.dumps(r, ensure_ascii=False, indent=1, default=str)[:6000])
    if a.publish:
        print(publish(a.date, a.root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
