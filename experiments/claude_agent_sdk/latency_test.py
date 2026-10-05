"""Latency + timeout/cleanup.
Always (no credentials used): timeout/cleanup with the REAL CLI — a 3 s timeout fires during CLI start-up;
the provider must raise LLMTimeout and leave no claude.exe process behind. Also measures locked-down CLI
start-up time (no-credential run, ends at "Not logged in").
With ANTHROPIC_API_KEY: 20+ real calls -> p50 / p95 / max, timeouts, retries."""
import json
import os
import statistics
import sys
import time

from _common import FACTS, blocked_if_no_key, raw_call, write
from auth_probe import count_claude_procs
from agent.llm.base import LLMError, LLMRequest, LLMTimeout


def timeout_cleanup() -> dict:
    from agent.llm.providers import claude_agent_sdk as M
    import _common
    before = count_claude_procs()
    p = M.ClaudeAgentSDKProvider(None, _common.CFG)
    req = LLMRequest(task="market_narrator", system="s", prompt="{}", prompt_version="t", timeout=3)
    sb = p.make_sandbox(req, None)
    t0 = time.perf_counter()
    try:
        p._run(req, sb, None, "", [])
        outcome = "NO_TIMEOUT"
    except LLMTimeout:
        outcome = "LLMTimeout"
    except LLMError as e:
        outcome = f"{type(e).__name__}: {str(e)[:120]}"
    el = time.perf_counter() - t0
    time.sleep(3)
    after = count_claude_procs()
    import shutil
    __import__('agent.llm.providers.claude_agent_sdk', fromlist=['x']).remove_sandbox(sb)
    leftovers = [x.name for x in sb.parent.iterdir()] if sb.parent.exists() else []
    return {"outcome": outcome, "elapsed_sec": round(el, 2), "procs_before": before, "procs_after": after,
            "orphan_process": after > before >= 0, "sandbox_leftovers": leftovers}


def startup_time(n: int = 3) -> dict:
    from agent.llm.providers import claude_agent_sdk as M
    import _common
    xs = []
    for _ in range(n):
        p = M.ClaudeAgentSDKProvider(None, _common.CFG)
        req = LLMRequest(task="market_narrator", system="s", prompt="{}", prompt_version="t", timeout=120)
        sb = p.make_sandbox(req, None)
        t0 = time.perf_counter()
        try:
            p._run(req, sb, None, "", [])
        except LLMError:
            pass
        xs.append(round(time.perf_counter() - t0, 2))
        import shutil
        __import__('agent.llm.providers.claude_agent_sdk', fromlist=['x']).remove_sandbox(sb)
    return {"no_credential_round_trip_sec": xs, "median": statistics.median(xs)}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        res = {"timeout_cleanup": timeout_cleanup(), "cli_startup": startup_time()}
    finally:
        if saved:
            os.environ["ANTHROPIC_API_KEY"] = saved
    if not blocked_if_no_key("latency_test_live"):
        lat, errs = [], {}
        for _ in range(20):
            t0 = time.perf_counter()
            try:
                raw_call(FACTS, system="Return the JSON narrative.")
                lat.append(time.perf_counter() - t0)
            except LLMError as e:
                errs[type(e).__name__] = errs.get(type(e).__name__, 0) + 1
        lat.sort()
        res["live"] = {"calls": 20, "ok": len(lat), "errors": errs,
                       "p50": round(lat[len(lat) // 2], 2) if lat else None,
                       "p95": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 2) if lat else None,
                       "max": round(lat[-1], 2) if lat else None}
    write("latency_test", res)
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
