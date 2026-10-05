"""3-day smoke / 15-day narrative replay: Template vs Claude Agent SDK narrative on W5 days (Round 06A).

  ..\\..\\.venv\\Scripts\\python.exe narrative_replay.py --days 3       (real SDK; needs ANTHROPIC_API_KEY)
  ..\\..\\.venv\\Scripts\\python.exe narrative_replay.py --days 15
  ..\\..\\.venv\\Scripts\\python.exe narrative_replay.py --days 3 --self-test
        harness self-test: the REAL provider code path (options, sandbox, error mapping, LLMClient, grounding,
        invariance checks) with a FAKE SDK transport answered by the deterministic mock. NOT Claude output.

Checks per day (agent/ops/llm_review.py): portfolio / orders / cash / Active Share / posture identical,
deterministic A–I checks (sources, fact ids, numbers, tickers, instructions, decisions unchanged, market view,
counter-evidence, validator). Real outputs: reports/round06a_sdk_replay/, reports/human_review_sdk/.
"""
import argparse
import json
import sys

from _common import CFG, OUT, ROOT, blocked_if_no_key, write
from agent.ops.llm_review import run_review
from agent.llm.providers.claude_agent_sdk import ClaudeAgentSDKProvider


def fake_sdk_query():
    sys.path.insert(0, str(ROOT / "tests" / "llm"))
    from test_claude_agent_sdk import fake_query_from_mock
    return fake_query_from_mock()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    cfg = dict(CFG, enabled=True)
    if a.self_test:
        import os
        os.environ.setdefault("ANTHROPIC_API_KEY", "self-test-dummy-not-a-key")   # fake transport: never sent anywhere
        prov = ClaudeAgentSDKProvider(None, cfg, query_fn=fake_sdk_query())
        out = OUT / f"self_test_{a.days}d"
        s = run_review(days=a.days, llm_config="config/llm_claude_agent_sdk.yaml", provider_instance=prov,
                       replay_run="sim_runs/round06_baseline_quant_v1", out_dir=out, human_review_dir=out / "human_review",
                       label="FAKE_SDK_SELF_TEST")
        s["label"] = "FAKE_SDK_SELF_TEST (deterministic mock behind the SDK provider code path; NOT Claude output)"
        write(f"narrative_replay_self_test_{a.days}d", s)
        print(json.dumps({k: s[k] for k in ("days", "invariance_failures", "order_invariance_rate", "validation_rate",
                                             "numeric_grounding_rate", "fallback_rate")}, ensure_ascii=False))
        return 0
    name = f"narrative_replay_{a.days}d"
    if blocked_if_no_key(name):
        rep = ROOT / "reports" / "human_review_sdk"
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "README.md").write_text(
            "# Human review — Claude Agent SDK narrative\n\nREAL status: **BLOCKED (AUTH_BLOCKED_NO_API_KEY)**. "
            "No real Claude Agent SDK call has been made, so there is nothing to review.\n\nAfter an Anthropic API key "
            "(Claude Console) is placed in `.env`:\n\n    cd experiments\\claude_agent_sdk\n"
            "    ..\\..\\.venv\\Scripts\\python.exe narrative_replay.py --days 3\n"
            "    ..\\..\\.venv\\Scripts\\python.exe narrative_replay.py --days 15\n\n"
            "One `YYYY-MM-DD_review.md` per day will appear here (facts, template vs SDK narrative, A–I checks).\n",
            encoding="utf-8")
        return 0
    prov = ClaudeAgentSDKProvider(None, cfg)
    out = ROOT / "reports" / "round06a_sdk_replay" / f"{a.days}d"
    s = run_review(days=a.days, llm_config="config/llm_claude_agent_sdk.yaml", provider_instance=prov,
                   replay_run="sim_runs/round06_baseline_quant_v1", out_dir=out,
                   human_review_dir=ROOT / "reports" / "human_review_sdk")
    write(name, s)
    print(json.dumps({k: s[k] for k in ("days", "invariance_failures", "order_invariance_rate", "validation_rate",
                                         "numeric_grounding_rate", "fallback_rate", "latency_max")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
