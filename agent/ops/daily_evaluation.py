"""Round 08-B..L: next-day evaluation of the PRECOMPETITION paper run (after T's close, task 17:00).

previous evening's FINAL paper prediction for T  +  paper settlement of T-1 (or initial cash, only when the
prediction itself started from initial cash — verified through the package's settlement_hash)
  -> existing deterministic simulator agent.sim.settle.settle (T VWAP fills, fees, tax, whole lots,
     corporate actions)  -> end-of-day holdings / cash / NAV
  -> data/paper_ledger/settlement/<T>.json   (separate PAPER ledger; never data/settlement/, so paper results
     can never be mistaken for the competition ledger; the 19:30 run reads it via --replay-run)
  -> reports/daily_evaluations/<T>_evaluation.md + logs/evaluation/latest_status.json

Evaluates decisions, never changes them. KPI = NAV / return / MDD / turnover / fees / compliance; the share of
holdings that went up is reported as DIAGNOSTIC ONLY. Everything is labelled PRECOMPETITION_PAPER_RUN.
Statuses: PASS | BLOCKED | FAILED | SKIPPED.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.config import D  # noqa: E402
from agent.ops.common import TPE, load_ops_config, sha256_file, ymd  # noqa: E402

LABEL = "PRECOMPETITION_PAPER_RUN"
OFFICIAL_LABEL = "COMPETITION_DAY_ESTIMATE"     # start = the competition settlement ledger (official DataPack)
LEDGER = ROOT / "data" / "paper_ledger"                 # sim-run layout: <LEDGER>/settlement/<date>.json
REPORT_DIR = ROOT / "reports" / "daily_evaluations"
LOG_DIR = ROOT / "logs" / "evaluation"
EVAL_HOUR = (17, 0)
STATUSES = ("PASS", "BLOCKED", "FAILED", "SKIPPED")


@dataclass
class Paths:
    ledger: Path = LEDGER
    reports: Path = REPORT_DIR
    logs: Path = LOG_DIR

    @property
    def latest(self) -> Path:
        return self.logs / "latest_status.json"

    @property
    def history(self) -> Path:
        return self.logs / "history.jsonl"

    def settlement(self, d: str) -> Path:
        return self.ledger / "settlement" / f"{d}.json"


# ----------------------------------------------------------------------------- date logic (pure)
def plan(now: datetime, hol: set[str], hm: tuple[int, int] = EVAL_HOUR) -> dict:
    """Evaluation date = today once 17:00 has passed. A start after midnight for yesterday's 17:00 is
    MISSED_PREVIOUS_DAY (never replayed automatically); non-trading days are SKIPPED."""
    from agent.ops.scheduled_run import is_trading_day
    today = now.date()
    due = datetime(today.year, today.month, today.day, *hm, tzinfo=TPE)
    ev_day = today if now >= due else today - timedelta(days=1)
    out = {"evaluation_date": ev_day.isoformat(), "scheduled_time": datetime(ev_day.year, ev_day.month, ev_day.day,
                                                                             *hm, tzinfo=TPE).isoformat(),
           "action": "RUN", "reason": None}
    if ev_day != today:
        out.update(action="SKIP", reason="MISSED_PREVIOUS_DAY")
    elif not is_trading_day(ev_day, hol):
        out.update(action="SKIP", reason="NO_TRADING_DAY")
    return out


def read_history(paths: Paths) -> list[dict]:
    if not paths.history.exists():
        return []
    out = []
    for line in paths.history.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def already_passed(ev_date: str, prediction_sha: str | None, history: list[dict]) -> bool:
    return any(h.get("evaluation_date") == ev_date and h.get("status") == "PASS"
               and h.get("prediction_sha256") == prediction_sha for h in history)


# ----------------------------------------------------------------------------- core evaluation
def _etf_benchmarks(store, as_of: str) -> dict[str, dict]:
    e = store.load("etf_holdings")
    if "synthetic" in e:
        e = e[~e["synthetic"]]
    e = e[e["date"] <= as_of]
    if not len(e):
        return {}
    last = e.groupby("etf")["date"].transform("max")
    e = e[e["date"] == last]
    return {etf: {str(r.ticker): D(str(r.weight)) for r in g.itertuples()} for etf, g in e.groupby("etf")}


def evaluate(ev_date: str, *, ops_cfg: dict | None = None, store=None, paths: Paths | None = None,
             refresh: bool = False, force: bool = False) -> dict:
    """Pure-ish core: returns the status record (also writes ledger + report on PASS)."""
    from agent.competition_day import settlement_hash
    from agent.data.loaders import HistoryStore
    from agent.engine.active_share import compute_official_active_share
    from agent.engine.rules import load_rulebook
    from agent.ops.package_submission import active_final
    from agent.pipeline import day_market, update_state_after_settlement
    from agent.sim.calendar import TradingCalendar
    from agent.sim.models import Settlement
    from agent.sim.settle import settle
    ops_cfg = ops_cfg or load_ops_config()
    paths = paths or Paths()
    store = store or HistoryStore()
    rb = load_rulebook()
    rec = {"evaluation_date": ev_date, "label": LABEL, "status": None, "blocked_reason": None}
    # 1. the prediction for this date (the previous evening's FINAL paper candidate)
    fin = active_final(ev_date, ops_cfg)
    if fin is None:
        rec.update(status="SKIPPED", blocked_reason="NO_PREDICTION_FOR_DATE")
        return rec
    from agent.ops.common import ops_path
    pkg = ops_path(ops_cfg, "submissions_dir") / ymd(ev_date) / "candidates" / fin["run_id"]
    doc = json.loads((pkg / fin["file"]).read_text(encoding="utf-8"))
    meta = json.loads((pkg / "run_metadata.json").read_text(encoding="utf-8"))
    state = json.loads((pkg / "agent_state.json").read_text(encoding="utf-8")) if (pkg / "agent_state.json").exists() else {}
    rec.update(prediction_date=str(meta.get("generated_at", ""))[:10], prediction_file=fin["path"],
               prediction_sha256=fin["sha256"], prediction_run_id=fin["run_id"], dplan_version=doc.get("schema_version"))
    if doc.get("trade_date") != ev_date:
        rec.update(status="BLOCKED", blocked_reason=f"DATE_MISMATCH dplan trade_date {doc.get('trade_date')}")
        return rec
    if not force and already_passed(ev_date, fin["sha256"], read_history(paths)):
        rec.update(status="SKIPPED", blocked_reason="SKIP_ALREADY_PASSED")
        return rec
    # 2. actual market data of the evaluation date (after close). A date that merely EXISTS is not enough: a
    #    partially fetched day (2026-10-16: TWSE failed, TPEx stored) is re-fetched and must be COMPLETE (P-2).
    from agent.ops.market_coverage import day_coverage, summary_line
    if refresh and (ev_date not in set(store.dates("daily_prices"))
                    or day_coverage(store, ev_date, ops_cfg=ops_cfg)["status"] != "COMPLETE"):
        try:
            from agent.ops.refresh_daily import refresh as do_refresh
            nxt = (date.fromisoformat(ev_date) + timedelta(days=1)).isoformat()
            do_refresh(nxt, store=store, only={"twse_prices", "tpex_prices", "corporate_actions"}, ops_cfg=ops_cfg)
            store._cache.clear()
        except Exception as e:  # noqa: BLE001
            rec["market_data_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    days = store.dates("daily_prices")
    if ev_date not in set(days):
        rec.update(status="BLOCKED", blocked_reason="MARKET_DATA_NOT_AVAILABLE", market_data="MISSING")
        return rec
    cov = day_coverage(store, ev_date, ops_cfg=ops_cfg)
    if cov["status"] != "COMPLETE":
        rec.update(status="BLOCKED", blocked_reason="MARKET_DATA_INCOMPLETE", market_data=summary_line(cov))
        return rec
    mkt = day_market(store, ev_date)
    need = {o["ticker"] for o in doc.get("orders", [])}
    missing_px = sorted(t for t in need if t not in mkt.close)
    rec["market_data"] = "OK" + (f" (no close for {missing_px})" if missing_px else "")
    # 3. starting point: must be exactly the one the prediction was built from (settlement_hash)
    cal = TradingCalendar(days)
    prev_date = cal.prev(ev_date)
    cands = []
    if paths.settlement(prev_date).exists():
        cands.append(("PAPER_LEDGER", Settlement.load(paths.settlement(prev_date))))
    try:      # COMPETITION: the prediction starts from the settlement ledger (official DataPack accepted by reconcile)
        from agent.ops.settlement import load_internal
        official = load_internal(prev_date, ops_cfg)
    except Exception:  # noqa: BLE001
        official = None
    if official is not None:
        cands.append(("OFFICIAL_SETTLEMENT", official))
    cands.append(("INITIAL_CASH", Settlement.initial(prev_date, rb.rules.initial_cash)))
    want = meta.get("settlement_hash")
    match = next(((src, s) for src, s in cands if settlement_hash(s) == want), None)
    if match is None:
        rec.update(status="BLOCKED", blocked_reason="SETTLEMENT_CHAIN_MISMATCH", start_candidates=[c[0] for c in cands])
        return rec
    start_src, prev = match
    rec.update(start_source=start_src, previous_date=prev_date)
    if start_src == "OFFICIAL_SETTLEMENT":
        rec["label"] = OFFICIAL_LABEL
    # every held ticker needs a valid close, every ordered ticker a valid vwap/volume, on the evaluation date
    hcov = day_coverage(store, ev_date, holdings=[t for t, n in prev.holdings.items() if int(n) > 0],
                        order_tickers=need, ops_cfg=ops_cfg)
    if hcov["status"] != "COMPLETE":
        rec.update(status="BLOCKED", blocked_reason="MARKET_DATA_INCOMPLETE", market_data=summary_line(hcov))
        return rec
    # 4. execution + settlement with the EXISTING deterministic simulator
    s = settle(prev, doc.get("orders", []), mkt, rb)
    s.agent_state = update_state_after_settlement(state or prev.agent_state, prev.holdings, s.holdings, ev_date)
    rec["execution"] = ("VOID" if s.trades_void else
                        f"{sum(1 for x in s.executions if x.get('vwap'))} filled / {len(doc.get('orders', []))} orders")
    # 5. NAV reconciliation (independent recomputation)
    recomputed = s.cash + sum((D(n) * mkt.close[t] for t, n in s.holdings.items() if t in mkt.close), D(0))
    nav_ok = abs(recomputed - s.nav) <= D(1)
    rec["settlement"] = "PASS" if nav_ok else f"NAV_MISMATCH recomputed {recomputed} vs {s.nav}"
    if not nav_ok:
        rec.update(status="FAILED", blocked_reason="NAV_RECONCILIATION_FAILED")
        return rec
    # 6. metrics
    init = s.initial_nav or rb.rules.initial_cash
    weights = {t: D(n) * mkt.close[t] / s.nav for t, n in s.holdings.items() if t in mkt.close}
    asr = compute_official_active_share(weights, _etf_benchmarks(store, ev_date), rb.active_etfs, 15,
                                        s.cash / s.nav, None, True, ev_date)
    rec.update(nav=str(s.nav.quantize(D("0.01"))), daily_return=float(s.nav / prev.nav - 1),
               cumulative_return=float(s.nav / D(init) - 1), mdd=float(D(s.mdd.get("include_initial_nav_true", 0))),
               turnover=float(s.turnover), fees=float(s.fees), tax=float(s.tax), cash_weight=float(s.cash / s.nav),
               holding_count=len(s.holdings),
               active_share=None if asr.minimum_active_share is None else float(asr.minimum_active_share),
               active_share_vs=asr.benchmark_ticker,
               compliance_warnings=[w.get("rule") for w in s.warnings], dq=s.dq)
    as_ok = rec["active_share"] is None or rec["active_share"] >= float(rb.rules.active_share_min)
    rec["compliance"] = "PASS" if (not s.warnings and not s.dq and as_ok) else "BLOCKED"
    # contributions: (end value - start value - net purchase cost at VWAP) / previous NAV
    pclose = day_market(store, prev_date).close if prev_date in set(days) else {}
    flows: dict[str, Decimal] = {}
    for x in s.executions:
        if x.get("vwap"):
            sign = 1 if x["side"] == "BUY" else -1
            flows[x["ticker"]] = flows.get(x["ticker"], D(0)) + sign * D(x["shares"]) * D(x["vwap"])
    rows = []
    for t in sorted(set(prev.holdings) | set(s.holdings) | set(flows)):
        end_v = D(s.holdings.get(t, 0)) * mkt.close.get(t, D(0))
        start_v = D(prev.holdings.get(t, 0)) * pclose.get(t, D(0))
        contrib = (end_v - start_v - flows.get(t, D(0))) / prev.nav
        ret = (float(mkt.close[t] / pclose[t] - 1) if t in pclose and t in mkt.close and pclose[t] else None)
        rows.append({"ticker": t, "weight": float(weights.get(t, 0)), "daily_return": ret, "contribution": float(contrib)})
    rec["holdings_result"] = rows
    held = [r for r in rows if r["weight"] > 0 and r["daily_return"] is not None]
    rec["positive_holding_ratio_diagnostic_only"] = (sum(1 for r in held if r["daily_return"] > 0) / len(held)) if held else None
    expl = sum(r["contribution"] for r in rows) - float((s.fees + s.tax) / prev.nav)
    rec["return_attribution_check"] = "PASS" if abs(expl - rec["daily_return"]) < 1e-6 else f"DIFF {expl - rec['daily_return']:.2e}"
    # 7. persist ledger (old copy kept if superseded) + report
    if start_src != "OFFICIAL_SETTLEMENT":        # a competition-day estimate never enters the PAPER ledger
        dst = paths.settlement(ev_date)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst.replace(dst.with_name(f"{ev_date}_superseded_{datetime.now(TPE):%Y%m%d_%H%M%S}.json.bak"))
        s.save(dst)
        rec["ledger_file"] = str(dst)
    rec["report_file"] = str(write_report(rec, paths))
    rec["status"] = "PASS" if rec["compliance"] == "PASS" else "BLOCKED"
    if rec["status"] == "BLOCKED":
        rec["blocked_reason"] = "COMPLIANCE: " + ",".join(rec["compliance_warnings"] or ["ACTIVE_SHARE"])
    return rec


def write_report(r: dict, paths: Paths) -> Path:
    from agent.engine.rules import load_rulebook
    names = {t: v.get("name", "") for t, v in load_rulebook().universe.items()}
    rows = r["holdings_result"]
    pos = sorted(rows, key=lambda x: -x["contribution"])[:5]
    neg = sorted(rows, key=lambda x: x["contribution"])[:5]

    asv = "-" if r["active_share"] is None else f"{r['active_share']:.2%}"

    def pct(x):
        return "-" if x is None else f"{x:+.2%}"
    label = r.get("label") or LABEL
    banner = ("賽前紙上交易驗證，**不是正式比賽成績**。只驗證前一晚的決策，不修改策略。" if label == LABEL else
              "正式比賽日預估：起點為官方 DataPack 結算（settlement ledger），以收盤價與同一套模擬器推算，"
              "**不是官方結算**（官方結算以下一份 DataPack 為準，不寫入 paper ledger）。只驗證已提交的決策，不修改策略。")
    L = [f"# Daily Evaluation — {r['evaluation_date']}（{label}）", "",
         f"> **{label}** — {banner}AI 產生內容，需人工審閱。", "",
         "## Previous prediction", "", "| 項目 | 值 |", "|---|---|",
         f"| Prediction file | `reports/daily_predictions/{r['evaluation_date']}_prediction.md` |",
         f"| D-Plan file | `{r['prediction_file']}`（v{r.get('dplan_version')}） |",
         f"| Prediction generated | {r.get('prediction_date')} |",
         f"| Starting point | {r.get('start_source')}（{r.get('previous_date')}） |",
         f"| Execution | {r.get('execution')} |", "",
         "## Actual result", "", "| KPI | 值 |", "|---|---|",
         f"| NAV | {float(r['nav']):,.0f} |", f"| Daily return | {pct(r['daily_return'])} |",
         f"| Cumulative return | {pct(r['cumulative_return'])} |", f"| MDD | {r['mdd']:.2%} |",
         f"| Turnover | {r['turnover']:.2%} |", f"| Fees | {r['fees']:,.0f} |", f"| Tax | {r['tax']:,.0f} |",
         f"| Cash weight | {r['cash_weight']:.2%} |", f"| Holdings | {r['holding_count']} |",
         f"| Active Share (official, end of day) | {asv}（{r.get('active_share_vs')}） |",
         f"| NAV reconciliation | {r['settlement']} |", f"| Return attribution check | {r['return_attribution_check']} |",
         f"| Positive holding ratio（diagnostic only） | {pct(r['positive_holding_ratio_diagnostic_only']).lstrip('+') if r['positive_holding_ratio_diagnostic_only'] is not None else '-'} |",
         "", f"## Compliance: **{r['compliance']}**" + (f"（{r['compliance_warnings']}）" if r['compliance_warnings'] else ""), "",
         "## Holdings result", "", "| Ticker | Name | Weight | Daily return | Contribution |", "|---|---|---|---|---|"]
    L += [f"| {x['ticker']} | {names.get(x['ticker'], '')} | {x['weight']:.2%} | {pct(x['daily_return'])} | {x['contribution']:+.3%} |"
          for x in sorted(rows, key=lambda x: -x["weight"])]
    L += ["", "## Largest positive contributors", ""] + [f"- {x['ticker']} {names.get(x['ticker'], '')} {x['contribution']:+.3%}" for x in pos]
    L += ["", "## Largest negative contributors", ""] + [f"- {x['ticker']} {names.get(x['ticker'], '')} {x['contribution']:+.3%}" for x in neg]
    L += ["", f"## Overall: **{'READY' if r['compliance'] == 'PASS' and r['settlement'] == 'PASS' else 'BLOCKED'}**", ""]
    paths.reports.mkdir(parents=True, exist_ok=True)
    p = paths.reports / f"{r['evaluation_date']}_evaluation.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


# ----------------------------------------------------------------------------- scheduled entry point
class _Lock:
    def __init__(self, p: Path):
        self.p = p

    def __enter__(self):
        self.p.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = datetime.now().timestamp() - self.p.stat().st_mtime
            if age < 3 * 3600:
                raise
            self.p.unlink()
            self.fd = os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        return self

    def __exit__(self, *a):
        os.close(self.fd)
        self.p.unlink(missing_ok=True)


def run(now: datetime | None = None, paths: Paths | None = None, ev_date: str | None = None,
        force: bool = False) -> dict:
    from agent.ops.scheduled_run import holidays
    now = now or datetime.now(TPE)
    paths = paths or Paths()
    paths.logs.mkdir(parents=True, exist_ok=True)
    log = paths.logs / f"evaluation_{now:%Y%m%d_%H%M%S}.log"
    started = now.replace(microsecond=0).isoformat()
    if ev_date is None:
        p = plan(now, holidays())
        ev_date = p["evaluation_date"]
        skip = p["reason"] if p["action"] == "SKIP" else None
    else:
        skip = None
    rec = {"evaluation_date": ev_date, "label": LABEL, "started_at": started}
    try:
        if skip:
            rec.update(status="SKIPPED", blocked_reason=skip)
        else:
            with _Lock(paths.logs / "evaluation.lock"):
                rec.update(evaluate(ev_date, paths=paths, refresh=True, force=force))
    except FileExistsError:
        rec.update(status="SKIPPED", blocked_reason="ANOTHER_EVALUATION_RUNNING")
    except Exception as e:  # noqa: BLE001
        import traceback
        rec.update(status="FAILED", error_message=f"{type(e).__name__}: {str(e)[:300]}")
        with open(log, "a", encoding="utf-8") as f:
            f.write(traceback.format_exc())
    rec["finished_at"] = datetime.now(TPE).replace(microsecond=0).isoformat()
    rec["log_file"] = str(log)
    assert rec["status"] in STATUSES
    keys = ["evaluation_date", "prediction_date", "started_at", "finished_at", "market_data", "execution",
            "settlement", "nav", "daily_return", "cumulative_return", "mdd", "turnover", "fees", "tax",
            "compliance", "active_share", "report_file", "status", "blocked_reason", "error_message"]
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"{'LABEL':<20} {rec.get('label') or LABEL}\n")
        for k in keys:
            f.write(f"{k.upper():<20} {rec.get(k, '-') if rec.get(k) is not None else '-'}\n")
    slim = {k: v for k, v in rec.items() if k != "holdings_result"}
    slim["return"] = rec.get("daily_return")
    paths.latest.write_text(json.dumps(slim, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    with open(paths.history, "a", encoding="utf-8") as f:
        f.write(json.dumps(slim, ensure_ascii=False, default=str) + "\n")
    return rec


def check(now: datetime | None = None, paths: Paths | None = None) -> dict:
    from agent.ops.scheduled_run import holidays
    now = now or datetime.now(TPE)
    paths = paths or Paths()
    p = plan(now, holidays())
    latest = json.loads(paths.latest.read_text(encoding="utf-8")) if paths.latest.exists() else None
    if p["action"] == "RUN" and (not latest or latest.get("evaluation_date") != p["evaluation_date"]):
        return {"status": "MISSED", "latest": latest, "recommended_action": "MANUAL_RERUN_RECOMMENDED",
                "evaluation_date": p["evaluation_date"]}
    st = (latest or {}).get("status", "NONE")
    rec = "MANUAL_RERUN_RECOMMENDED" if st in ("BLOCKED", "FAILED") else "NONE"
    return {"status": st, "latest": latest, "recommended_action": rec,
            "evaluation_date": (latest or {}).get("evaluation_date")}


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--date", default=None, help="evaluate a specific date (manual); default = today after 17:00")
    ap.add_argument("--force", action="store_true", help="re-evaluate even if already PASS (manual only)")
    a = ap.parse_args(argv)
    if a.check:
        print(json.dumps(check(), ensure_ascii=False, default=str))
        return 0
    r = run(ev_date=a.date, force=a.force)
    print(f"EVALUATION {r['evaluation_date']} {r['status']} {r.get('blocked_reason') or ''} report={r.get('report_file', '-')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
