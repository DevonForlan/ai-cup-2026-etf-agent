"""Usage / cost metadata exposed by the SDK (ResultMessage.usage, model_usage, total_cost_usd). Requires
ANTHROPIC_API_KEY. Without a key: records which fields the SDK declares (from its types), no numbers."""
import dataclasses
import json
import sys

from _common import FACTS, blocked_if_no_key, raw_call, write
from agent.llm.base import LLMError


def declared_fields() -> dict:
    from claude_agent_sdk import ResultMessage
    f = {x.name for x in dataclasses.fields(ResultMessage)}
    return {k: k in f for k in ("usage", "model_usage", "total_cost_usd", "duration_ms", "duration_api_ms",
                                "num_turns", "session_id")}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    res = {"declared_by_sdk": declared_fields()}
    if not blocked_if_no_key("usage_test_live"):
        try:
            r = raw_call(FACTS, system="Return the JSON narrative.")
            m = r.provider_meta
            res["live"] = {"input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                           "cache_read_input_tokens": m.get("cache_read_input_tokens"),
                           "total_cost_usd": m.get("total_cost_usd") if m.get("total_cost_usd") is not None
                           else "NOT_EXPOSED_BY_SDK", "model": r.model_version}
        except LLMError as e:
            res["live"] = {"error": f"{type(e).__name__}: {e}"}
    write("usage_test", res)
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
