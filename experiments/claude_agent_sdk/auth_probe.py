"""Auth probe. Prints ONLY: SDK_INSTALLED, SDK_VERSION, CLAUDE_CODE_VERSION, AUTH_MODE, AUTH_AVAILABLE,
MODEL_ACCESS (+ isolation result). Never prints or reads any token, key, session or credential file.

Isolation check (runs even without a key): spawn the locked-down CLI (--bare, empty CLAUDE_CONFIG_DIR,
ANTHROPIC_API_KEY blank) through the real SDK and confirm it can NOT authenticate, i.e. the stored Claude Code
subscription login is unreachable from the Narrative Agent. No credential is used, so no model call happens.

  .venv\\Scripts\\python.exe experiments\\claude_agent_sdk\\auth_probe.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

from _common import ROOT, raw_call, write  # noqa: F401
from agent.llm.base import LLMError
from agent.llm.env import get_key
from agent.llm.providers.claude_agent_sdk import cli_version, resolve_cli, sdk_version


def count_claude_procs() -> int:
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq claude.exe", "/FO", "CSV", "/NH"], capture_output=True,
                           text=True, timeout=30)
        return sum(1 for line in r.stdout.splitlines() if line.lower().startswith('"claude.exe"'))
    except Exception:  # noqa: BLE001
        return -1


def isolation_check() -> dict:
    """Real SDK + real CLI with NO credentials: must fail with an auth error, quickly, and leave no process."""
    from agent.llm.providers import claude_agent_sdk as M
    before = count_claude_procs()
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    orig = M.get_key
    M.get_key = lambda name: "" if name == "ANTHROPIC_API_KEY" else orig(name)      # blank key, bypass guard
    p = M.ClaudeAgentSDKProvider(None, json.loads(json.dumps(__import__("_common").CFG)))
    req = M.LLMRequest(task="market_narrator", system="Say OK.", prompt='{"facts": {}}', prompt_version="probe",
                       timeout=60)
    t0 = time.perf_counter()
    outcome, detail = "UNEXPECTED_SUCCESS", ""
    try:
        sb = p.make_sandbox(req, None)
        try:
            p._run(req, sb, None, "", [])
        finally:
            __import__('agent.llm.providers.claude_agent_sdk', fromlist=['x']).remove_sandbox(sb)
    except LLMError as e:
        outcome, detail = type(e).__name__, str(e)[:240]
    except Exception as e:  # noqa: BLE001
        outcome, detail = type(e).__name__, str(e)[:240]
    finally:
        M.get_key = orig
        if saved:
            os.environ["ANTHROPIC_API_KEY"] = saved
    time.sleep(2)
    after = count_claude_procs()
    return {"outcome": outcome, "detail": detail, "elapsed_sec": round(time.perf_counter() - t0, 1),
            "claude_processes_before": before, "claude_processes_after": after,
            "subscription_login_reachable": outcome == "UNEXPECTED_SUCCESS",
            "orphan_process": after > before >= 0}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cli = resolve_cli("auto")
    key = bool(get_key("ANTHROPIC_API_KEY"))
    res = {"SDK_INSTALLED": bool(sdk_version()), "SDK_VERSION": sdk_version(),
           "CLAUDE_CODE_VERSION": cli_version(cli), "CLI_RESOLVED": "native claude.exe" if cli else None,
           "AUTH_MODE": "API_KEY" if key else "NONE (API key absent; subscription login deliberately not used)",
           "AUTH_AVAILABLE": key, "MODEL_ACCESS": "NOT_TESTED_NO_API_KEY"}
    if key:
        try:
            r = raw_call({"facts": {"F1": {"statement": "test"}}}, task="probe", system="Reply with the word OK.")
            res["MODEL_ACCESS"] = f"OK ({r.model_version})"
        except LLMError as e:
            res["MODEL_ACCESS"] = f"FAILED {type(e).__name__}"
    res["ISOLATION_CHECK"] = isolation_check()
    for k, v in res.items():
        print(f"{k}: {v}")
    write("auth_probe", res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
