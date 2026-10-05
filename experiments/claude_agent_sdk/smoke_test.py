"""Smoke test: facts JSON only -> {market_view, counter_evidence, fact_refs}. No project access, no tools.
Requires ANTHROPIC_API_KEY (BLOCKED otherwise; nothing is spawned)."""
import sys

from _common import FACTS, blocked_if_no_key, raw_call, write
from agent.llm.base import LLMError


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if blocked_if_no_key("smoke_test"):
        return 0
    try:
        r = raw_call(FACTS, task="market_narrator",
                     system="Return JSON {market_view, counter_evidence, fact_refs} using only F1/F2.")
        write("smoke_test", {"status": "OK", "model": r.model_version, "response": r.text, "latency_sec": r.latency_sec,
                             "usage": r.provider_meta.get("usage")})
        print("smoke_test: OK", r.model_version, r.text[:300])
    except LLMError as e:
        write("smoke_test", {"status": "FAILED", "error": f"{type(e).__name__}: {e}"})
        print("smoke_test: FAILED", type(e).__name__, e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
