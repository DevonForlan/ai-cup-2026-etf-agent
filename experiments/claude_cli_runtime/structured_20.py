"""20 sequential calls, same realistic narrative input (NarrativeOut schema via the real market_narrator prompt).
Measures schema / grounding / unknown fact / numeric / ticker hallucination / parse failure / timeout /
non-zero exit / latency, and output variability across the repeated identical input."""
import difflib
import json
import statistics
import sys

from _common import call, grounded, grounding, provider, write
from agent.llm.client import load_prompt
from agent.llm.schemas import NarrativeOut

N = 20
PAYLOAD = {"facts": {
    "O1": {"statement": "2026-10-02 收盤：150 檔中站上 20 日均線比例 63.1%；上漲 75 檔、下跌 67 檔",
           "values": {"breadth_above_ma20_pct": 63.1, "advancers_1d": 75, "decliners_1d": 67}},
    "O2": {"statement": "20 日報酬中位數 +15.80%；5 日報酬中位數 +2.35%",
           "values": {"median_ret_20d_pct": 15.8, "median_ret_5d_pct": 2.35}},
    "O3": {"statement": "費城半導體指數隔夜 -0.40%；台指期夜盤 +0.12%", "values": {"sox_pct": -0.4, "txf_night_pct": 0.12}},
    "O4": {"statement": "2330 現權重 9.80%，2317 現權重 4.10%（本日不交易）", "values": {"w_2330": 9.8, "w_2317": 4.1}}},
    "quant_decision": {"regime": "risk_on", "posture": "hold", "orders": [], "cash_pct_est": 8.23}}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = provider()
    system, _, _ = load_prompt("market_narrator_v1")
    rows, texts = [], []
    for i in range(N):
        r = call(p, PAYLOAD, task="market_narrator", system=system)
        row = {"i": i, "ok": r["ok"], "latency": round(r["latency"], 2), "error": r.get("category") or r.get("error"),
               "exit_code": (r.get("meta") or {}).get("exit_code"), "model": r.get("model"),
               "tool_violations": (r.get("meta") or {}).get("tool_violations"),
               "in_tok": r.get("in_tok"), "out_tok": r.get("out_tok"),
               "cost": (r.get("meta") or {}).get("total_cost_usd")}
        if r["ok"]:
            obj = json.loads(r["text"])
            try:
                NarrativeOut.model_validate(obj)
                row["schema"] = True
            except Exception:  # noqa: BLE001
                row["schema"] = False
            g = grounding(PAYLOAD, obj)
            row.update(grounded=grounded(g), unknown_fact=bool(g["unknown_fact_ids"]),
                       numeric_halluc=bool(g["ungrounded_numbers"]), ticker_halluc=bool(g["new_tickers"]),
                       forbidden=g["forbidden_instruction"], fact_refs=sorted(obj.get("fact_refs") or []),
                       g=g)
            texts.append(obj.get("logic", ""))
        rows.append(row)
        print(i, row["ok"], row.get("schema"), row.get("grounded"), row["latency"], row["error"] or "", flush=True)
    ok = [r for r in rows if r["ok"]]
    lat = sorted(r["latency"] for r in ok)
    sims = [difflib.SequenceMatcher(None, a, b).ratio() for i, a in enumerate(texts) for b in texts[i + 1:]]
    res = {"calls": N, "ok": len(ok),
           "schema_pass_rate": sum(r.get("schema", False) for r in rows) / N,
           "grounding_pass_rate": sum(r.get("grounded", False) for r in rows) / N,
           "unknown_fact_rate": sum(r.get("unknown_fact", False) for r in ok) / N,
           "numeric_hallucination_rate": sum(r.get("numeric_halluc", False) for r in ok) / N,
           "ticker_hallucination_rate": sum(r.get("ticker_halluc", False) for r in ok) / N,
           "forbidden_wording_rate": sum(r.get("forbidden", False) for r in ok) / N,
           "parse_failure": sum(1 for r in rows if r["error"] in ("INVALID_JSON", "SCHEMA_FAIL")),
           "timeout": sum(1 for r in rows if r["error"] == "TIMEOUT"),
           "nonzero_exit": sum(1 for r in rows if r["exit_code"] not in (0, None)),
           "tool_violations": sum(r.get("tool_violations") or 0 for r in rows),
           "latency_p50": lat[len(lat) // 2] if lat else None,
           "latency_p95": lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else None,
           "latency_max": lat[-1] if lat else None,
           "variability": {"text_similarity_mean": round(statistics.mean(sims), 3) if sims else None,
                           "text_similarity_min": round(min(sims), 3) if sims else None,
                           "distinct_texts": len(set(texts)),
                           "fact_ref_sets": sorted({json.dumps(r.get("fact_refs")) for r in ok}),
                           "schema_keys_constant": True},
           "models": sorted({r["model"] for r in ok if r["model"]}),
           "cost_estimate_total_usd": round(sum(r["cost"] or 0 for r in ok), 4), "rows": rows, "sample_texts": texts[:5]}
    write("structured_20", res)
    print(json.dumps({k: v for k, v in res.items() if k not in ("rows", "sample_texts")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
