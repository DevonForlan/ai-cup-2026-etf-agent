"""Structured output: 20 calls through the REAL project path (LLMClient + NarrativeOut pydantic schema +
deterministic grounding validator, native SDK json_schema output). Counts schema pass, JSON parse failures,
unknown fields, unknown fact ids, numeric hallucinations. Requires ANTHROPIC_API_KEY."""
import json
import sys

from _common import blocked_if_no_key, client, write
from agent.llm.grounding import allowed_numbers, bad_refs, ungrounded_numbers
from agent.llm.schemas import NarrativeOut

N = 20
PAYLOAD = {"facts": {"O1": {"statement": "150 檔中站上 20 日均線比例 63.1%", "values": {"breadth_pct": 63.1}},
                     "O2": {"statement": "20 日報酬中位數 +15.80%", "values": {"median_ret_20d_pct": 15.8}}},
           "regime": "risk_on", "posture": "hold"}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if blocked_if_no_key("structured_output_test"):
        return 0
    from agent.llm.client import load_prompt
    c = client()
    req = c.request("market_narrator", "market_narrator_v1", PAYLOAD, ["O1", "O2"])
    allowed = allowed_numbers(PAYLOAD)
    rows = []
    for i in range(N):
        obj = c.generate_structured(req, NarrativeOut)
        if obj is None:
            rows.append({"i": i, "schema_pass": False})
            continue
        text = obj.logic + " " + (obj.counter_evidence or "")
        rows.append({"i": i, "schema_pass": True, "unknown_fact_ids": bad_refs(obj.fact_refs, {"O1", "O2"}),
                     "numeric_hallucination": ungrounded_numbers(text, allowed)})
    recs = c.logger.records
    res = {"calls": N, "schema_pass_rate": sum(r["schema_pass"] for r in rows) / N,
           "json_parse_failures": sum(1 for r in recs if r.get("status") == "format_error"),
           "unknown_fact_id_calls": sum(1 for r in rows if r.get("unknown_fact_ids")),
           "numeric_hallucination_calls": sum(1 for r in rows if r.get("numeric_hallucination")),
           "unknown_field_note": "NarrativeOut is a strict pydantic model (extra=forbid): unknown fields fail schema",
           "rows": rows}
    write("structured_output_test", res)
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
