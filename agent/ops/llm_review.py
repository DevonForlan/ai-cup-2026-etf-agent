"""Round 05 narrative review: template vs LLM narrative on replayed days (narrative ONLY: no event signal,
no Crash Guard change). Hard invariance: portfolio / orders / cash / every non-text field identical.

Deterministic quality checks (a second LLM is never the judge):
  A source refs resolve          B fact ids (basis/premise/inference refs) resolve
  C every number in LLM text is in the facts / template      D no ticker outside the D-Plan's tickers
  E no instruction contamination (reviewer FORBIDDEN regex)    F no decision modified (non-text fields equal)
  G market_view consistent (regime/stance/posture equal, no opposite-stance wording)
  H counter_evidence non-empty   I D-Plan validator PASS

Outputs (real provider):  reports/round05_llm_narrative_review.csv, reports/round05_llm_cost.csv,
                          reports/human_review/YYYY-MM-DD_review.md
With --provider mock the outputs go to reports/round05_mock_pipeline_check/ (mock is NOT an LLM).

  python agent\\ops\\llm_review.py --llm-config config\\llm_narrative_v1.yaml --provider google --days 15
  python agent\\ops\\llm_review.py --provider mock --days 10
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import re
import statistics
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT, load_strategy, load_universe  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.engine.rules import load_rulebook  # noqa: E402
from agent.llm.grounding import allowed_numbers, numbers_in  # noqa: E402
from agent.pipeline import llm_settings, run_day  # noqa: E402
from agent.research.reviewer import FORBIDDEN  # noqa: E402
from agent.sim.calendar import TradingCalendar  # noqa: E402
from agent.sim.models import Settlement  # noqa: E402

REVIEW_COLS = ["date", "provider", "model", "prompt_version", "calls", "tokens_in", "tokens_out", "latency_p50",
               "latency_max", "schema_valid", "grounding_pass", "numeric_grounding_pass", "source_reference_pass",
               "reviewer_pass", "fallback_used", "template_vs_llm_order_equal", "human_review_status"]
CHECK_COLS = ["A_source_refs", "B_fact_ids", "C_numbers", "D_tickers", "E_no_instruction", "F_decisions_unchanged",
              "G_market_view_consistent", "H_counter_evidence", "I_validator_pass"]
COST_COLS = ["date", "provider", "model", "requests", "input_tokens", "output_tokens", "price_in_usd_per_1m",
             "price_out_usd_per_1m", "daily_cost_usd"]
TICKER_RE = re.compile(r"(?<!\d)(\d{4}[A-Z]?)(?!\d)")
OPPOSITE = {"risk_on": re.compile(r"(看空|偏空|空頭|risk[-_ ]off|減碼)"),
            "risk_off": re.compile(r"(看多|偏多|多頭|risk[-_ ]on|加碼)")}


def text_fields(doc: dict) -> list[tuple[str, str]]:
    out = [("market_view.logic", doc["market_view"].get("logic") or ""),
           ("market_view.counter_evidence", doc["market_view"].get("counter_evidence") or "")]
    for i in doc["inferences"]:
        out += [(f"{i['inf_id']}.logic", i.get("logic") or ""), (f"{i['inf_id']}.counter_evidence", i.get("counter_evidence") or "")]
    return out


def strip_text(doc: dict) -> dict:
    d = copy.deepcopy(doc)
    d.pop("agent_metadata", None)
    d["market_view"].pop("logic", None)
    d["market_view"].pop("counter_evidence", None)
    for i in d["inferences"]:
        i.pop("logic", None)
        i.pop("counter_evidence", None)
    return d


def deterministic_checks(llm_doc: dict, tpl_doc: dict, validation_ok: bool, universe: set[str]) -> dict:
    src = {s["source_id"] for s in llm_doc["sources"]}
    obs = {o["obs_id"] for o in llm_doc["observations"]}
    inf = {i["inf_id"] for i in llm_doc["inferences"]}
    A = all(r in src for o in llm_doc["observations"] for r in o["source_ref"])
    B = (all(r in obs | inf for r in llm_doc["market_view"].get("basis_refs", []))
         and all(r in obs | inf for i in llm_doc["inferences"] for r in i.get("premise_refs", []))
         and all(r in inf for d in llm_doc["decisions"] for r in d.get("inference_refs", [])))
    facts = {"observations": llm_doc["observations"], "decisions": llm_doc["decisions"],
             "conclusions": [i.get("conclusion") for i in llm_doc["inferences"]],
             "market_view": {k: v for k, v in llm_doc["market_view"].items() if k not in ("logic", "counter_evidence")},
             "template_text": [t for _, t in text_fields(tpl_doc)], "trade_date": llm_doc["trade_date"]}
    allowed = allowed_numbers(facts)
    texts = text_fields(llm_doc)
    bad_nums = sorted({n for _, t in texts for n in numbers_in(t) if n not in allowed})
    doc_tickers = {d["ticker"] for d in llm_doc["decisions"]} | {o["ticker"] for o in llm_doc["orders"]} \
        | set(TICKER_RE.findall(json.dumps(llm_doc["observations"], ensure_ascii=False)))
    bad_tk = sorted({t for _, x in texts for t in TICKER_RE.findall(x) if t in universe and t not in doc_tickers})
    E = not any(FORBIDDEN.search(t) for _, t in texts)
    F = strip_text(llm_doc) == strip_text(tpl_doc)
    mv, tv = llm_doc["market_view"], tpl_doc["market_view"]
    opp = OPPOSITE.get(mv.get("regime", ""))
    G = all(mv.get(k) == tv.get(k) for k in ("regime", "stance", "posture", "basis_refs")) and \
        not (opp and opp.search(mv.get("logic") or ""))
    # H: counter_evidence is optional in the schema and the template leaves it null when the facts hold no
    # negative signal; the LLM must not DROP one the facts support (inventing one would be ungrounded).
    lt = dict(texts)
    H = all(lt.get(k, "").strip() for k, t in text_fields(tpl_doc) if k.endswith("counter_evidence") and t.strip())
    return {"A_source_refs": A, "B_fact_ids": B, "C_numbers": not bad_nums, "D_tickers": not bad_tk,
            "E_no_instruction": E, "F_decisions_unchanged": F, "G_market_view_consistent": G,
            "H_counter_evidence": H, "I_validator_pass": validation_ok,
            "_bad_numbers": bad_nums[:20], "_bad_tickers": bad_tk}


def _calls(log_root: Path, d: str) -> list[dict]:
    p = log_root / d.replace("-", "") / "calls.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def human_review_md(d: str, tpl: dict, llm: dict, chk: dict, provider: str, model: str, mock: bool) -> str:
    L = [f"# Narrative review {d}", ""]
    if mock:
        L += ["> **MOCK PROVIDER — NOT AN LLM.** Pipeline verification only; text quality says nothing about a real "
              "model. REAL_LLM_STATUS = BLOCKED_NO_API_KEY.", ""]
    L += [f"provider `{provider}` model `{model}`", "", "## Reviewer result (deterministic A–I)", "",
          "| check | result |", "|---|---|"]
    L += [f"| {k} | {'PASS' if chk[k] else '**FAIL**'} |" for k in CHECK_COLS]
    if chk["_bad_numbers"] or chk["_bad_tickers"]:
        L += ["", f"ungrounded numbers: {chk['_bad_numbers']}  unknown tickers: {chk['_bad_tickers']}"]
    L += ["", "## Narrative (template | LLM)", "", "| field | Template | LLM |", "|---|---|---|"]
    lt = dict(text_fields(llm))
    for k, t in text_fields(tpl):
        L.append(f"| {k} | {t.replace('|', '/')} | {lt.get(k, '').replace('|', '/')} |")
    L += ["", "## Facts (observations)", ""]
    L += [f"- **{o['obs_id']}** [{', '.join(o['source_ref'])}] {o['statement']}" for o in llm["observations"]]
    L += ["", "## Sources", ""]
    L += [f"- **{s['source_id']}** {s['name']} ({s['authority']}, as of {s['content_as_of']}) {s.get('url', '')}"
          for s in llm["sources"]]
    L += ["", "## Human review", "", "- [ ] text clearer than template   - [ ] no unsupported claim   "
          "- [ ] tone acceptable for the organizer", "- reviewer: ____  date: ____  verdict: APPROVE / REJECT", ""]
    return "\n".join(L)


def run_review(*, days: int = 15, llm_config: str = "config/llm_narrative_v1.yaml", provider: str | None = None,
               provider_instance=None, replay_run: str = "sim_runs/round05_baseline_quant_v1",
               strategy: str = "config/strategy_quant_v1.yaml", out_dir: Path | None = None,
               store: HistoryStore | None = None, team_id: str = "TEAM_SIM") -> dict:
    store = store or HistoryStore()
    rb = load_rulebook()
    cfg = load_strategy(strategy)
    run = ROOT / replay_run
    dates = sorted(p.stem for p in (run / "settlement").glob("*.json"))[:days]
    cal = TradingCalendar(store.dates("daily_prices"))
    universe = set(load_universe())
    work = Path(tempfile.mkdtemp(prefix="r5llm_"))
    log_root = work / "llm_logs"
    llm = llm_settings(cfg, "llm", provider, llm_config, provider_instance=provider_instance, log_root=log_root)
    if llm is None:
        raise SystemExit("LLM narrative not active (provider=template): set --provider or provider in the llm config")
    lc = llm["cfg"]
    pname, mock = lc.get("provider"), lc.get("provider") in ("mock", "replay")
    out_dir = out_dir or (ROOT / "reports" / "round05_mock_pipeline_check" if mock else ROOT / "reports")
    hr_dir = out_dir / "human_review"
    hr_dir.mkdir(parents=True, exist_ok=True)
    rows, cost_rows, invariance_fail = [], [], []
    for d in dates:
        p = cal.prev(d)
        sp = run / "settlement" / f"{p}.json"
        prev = Settlement.load(sp) if sp.exists() else Settlement.initial(p, rb.rules.initial_cash)
        r_t = run_day(d, store, copy.deepcopy(prev), rb, cfg, team_id=team_id, out_dir=work / "tpl", log_dir=None,
                      calendar=cal, light=True)
        r_l = run_day(d, store, copy.deepcopy(prev), rb, cfg, team_id=team_id, out_dir=work / "llm", log_dir=None,
                      calendar=cal, light=True, llm=llm)
        orders_eq = r_t.doc["orders"] == r_l.doc["orders"]
        port_eq = (r_t.result.est_holdings == r_l.result.est_holdings and r_t.result.est_cash == r_l.result.est_cash
                   and r_t.result.weights == r_l.result.weights)
        if not (orders_eq and port_eq):
            invariance_fail.append(d)
        chk = deterministic_checks(r_l.doc, r_t.doc, r_l.validation.ok, universe)
        calls = [c for c in _calls(log_root, d) if c.get("task", "").startswith(("market", "thesis", "narr"))] \
            or _calls(log_root, d)
        lat = sorted(c.get("latency_sec") or 0 for c in calls if c.get("status") in ("ok", "replay"))
        tin = sum(c.get("input_tokens") or 0 for c in calls)
        tout = sum(c.get("output_tokens") or 0 for c in calls)
        model = r_l.doc["agent_metadata"].get("model_version") or lc.get("model")
        pv = ",".join(sorted({c.get("prompt_version", "") for c in calls if c.get("prompt_version")}))
        rows.append({
            "date": d, "provider": pname, "model": model, "prompt_version": pv, "calls": len(calls),
            "tokens_in": tin, "tokens_out": tout,
            "latency_p50": round(statistics.median(lat), 3) if lat else "", "latency_max": round(max(lat), 3) if lat else "",
            "schema_valid": all(c.get("status") in ("ok", "replay") for c in calls) and bool(calls),
            "grounding_pass": chk["A_source_refs"] and chk["B_fact_ids"] and chk["D_tickers"],
            "numeric_grounding_pass": chk["C_numbers"], "source_reference_pass": chk["A_source_refs"],
            "reviewer_pass": chk["E_no_instruction"] and chk["G_market_view_consistent"] and chk["H_counter_evidence"],
            "fallback_used": not r_l.narrative_used_llm, "template_vs_llm_order_equal": orders_eq and port_eq,
            "human_review_status": "N/A_MOCK_NOT_AN_LLM" if mock else "PENDING",
            **{k: chk[k] for k in CHECK_COLS}})
        price = lc.get("price_usd_per_1m_tokens") or {}
        pin, pout = price.get("input"), price.get("output")
        cost_rows.append({"date": d, "provider": pname, "model": model, "requests": len(calls), "input_tokens": tin,
                          "output_tokens": tout, "price_in_usd_per_1m": pin if pin is not None else "",
                          "price_out_usd_per_1m": pout if pout is not None else "",
                          "daily_cost_usd": round((tin * pin + tout * pout) / 1e6, 6) if pin is not None and pout is not None
                          else "PRICE_NOT_CONFIGURED"})
        (hr_dir / f"{d}_review.md").write_text(human_review_md(d, r_t.doc, r_l.doc, chk, pname, model, mock),
                                               encoding="utf-8")
    review_csv = out_dir / "round05_llm_narrative_review.csv"
    with open(review_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_COLS + CHECK_COLS)
        w.writeheader()
        w.writerows(rows)
    priced = [c["daily_cost_usd"] for c in cost_rows if isinstance(c["daily_cost_usd"], float)]
    with open(out_dir / "round05_llm_cost.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COST_COLS)
        w.writeheader()
        w.writerows(cost_rows)
        w.writerow({"date": "ESTIMATED_24_DAY_TOTAL", "provider": pname,
                    "requests": round(statistics.mean([c["requests"] for c in cost_rows]) * 24, 1) if cost_rows else 0,
                    "input_tokens": round(statistics.mean([c["input_tokens"] for c in cost_rows]) * 24) if cost_rows else 0,
                    "output_tokens": round(statistics.mean([c["output_tokens"] for c in cost_rows]) * 24) if cost_rows else 0,
                    "daily_cost_usd": round(statistics.mean(priced) * 24, 4) if priced and len(priced) == len(cost_rows)
                    else "PRICE_NOT_CONFIGURED"})
    n = len(rows) or 1
    all_lat = [r["latency_max"] for r in rows if r["latency_max"] != ""]
    summary = {
        "provider": pname, "model": rows[0]["model"] if rows else None, "days": len(rows), "mock": mock,
        "invariance_failures": invariance_fail,
        "schema_failure_rate": 1 - sum(r["schema_valid"] for r in rows) / n,
        "validation_rate": sum(r["I_validator_pass"] for r in rows) / n,
        "order_invariance_rate": sum(r["template_vs_llm_order_equal"] for r in rows) / n,
        "numeric_grounding_rate": sum(r["numeric_grounding_pass"] for r in rows) / n,
        "hallucinated_ticker_days": sum(not r["D_tickers"] for r in rows),
        "hallucinated_source_days": sum(not r["A_source_refs"] for r in rows),
        "fallback_rate": sum(r["fallback_used"] for r in rows) / n,
        "latency_max": max(all_lat) if all_lat else None,
        "tokens_per_day": statistics.mean([r["tokens_in"] + r["tokens_out"] for r in rows]) if rows else 0,
        "checks_pass_rate": {k: sum(r[k] for r in rows) / n for k in CHECK_COLS},
        "outputs": {"review_csv": str(review_csv), "cost_csv": str(out_dir / "round05_llm_cost.csv"),
                    "human_review": str(hr_dir)}}
    (out_dir / "round05_llm_review_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    return summary


def write_blocked(status: str, provider: str | None, model: str | None, out_dir: Path | None = None) -> None:
    """Real LLM not runnable: write the official report files with an explicit BLOCKED row (no fake numbers)."""
    out_dir = out_dir or ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "round05_llm_narrative_review.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_COLS + CHECK_COLS)
        w.writeheader()
        w.writerow({"date": "ALL", "provider": provider, "model": model or "", "human_review_status": status})
    with open(out_dir / "round05_llm_cost.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COST_COLS)
        w.writeheader()
        w.writerow({"date": "ALL", "provider": provider, "model": model or "", "daily_cost_usd": status})
    hr = out_dir / "human_review"
    hr.mkdir(exist_ok=True)
    (hr / "README.md").write_text(
        f"# Human review — real LLM narrative\n\nREAL_LLM_STATUS = **{status}**\n\n"
        "No real-provider run was possible, so there is nothing to review yet. After an API key is configured "
        "(docs/REAL_LLM_SETUP.md) run:\n\n"
        "    .venv\\Scripts\\python.exe agent\\ops\\llm_review.py --llm-config config\\llm_narrative_v1.yaml "
        "--provider google --days 15\n\n"
        "One `YYYY-MM-DD_review.md` per day will appear here (template vs LLM side by side, facts, sources, "
        "deterministic reviewer A–I). Pipeline-only mock output: reports/round05_mock_pipeline_check/.\n",
        encoding="utf-8")


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm-config", default="config/llm_narrative_v1.yaml")
    ap.add_argument("--provider", default=None, help="override provider (google|openai|anthropic|mock)")
    ap.add_argument("--days", type=int, default=15)
    ap.add_argument("--replay-run", default="sim_runs/round05_baseline_quant_v1")
    a = ap.parse_args(argv)
    from agent.llm.client import load_llm_config, make_provider
    lc = load_llm_config(a.llm_config)
    if a.provider:
        lc["provider"] = a.provider
    if lc.get("provider") not in ("mock", "replay", "template"):
        from agent.llm.providers import http_providers as H
        cls = {"google": H.GeminiProvider, "gemini": H.GeminiProvider, "openai": H.OpenAIProvider,
               "anthropic": H.AnthropicProvider}[lc["provider"]]
        ok, why = cls("probe").available(), "BLOCKED_NO_API_KEY"   # presence only; the key is never printed
        if ok:
            try:
                make_provider(lc)
            except ValueError as e:               # e.g. model not pinned in the config
                ok, why = False, f"BLOCKED_CONFIG: {e}"
        if not ok:
            write_blocked(why, lc.get("provider"), lc.get("model"))
            print(f"REAL_LLM_STATUS = {why}  (no request was sent; reports written as BLOCKED)")
            return 3
    s = run_review(days=a.days, llm_config=a.llm_config, provider=a.provider, replay_run=a.replay_run)
    print(json.dumps(s, indent=1, ensure_ascii=False, default=str))
    if s["invariance_failures"]:
        print("INVARIANCE FAILURE on", s["invariance_failures"])
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
