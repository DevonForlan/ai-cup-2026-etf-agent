"""Claude Agent SDK narrative provider (Round 06A spike) — least-privilege, API-key-only.

Authentication (official guidance, code.claude.com/docs/en/agent-sdk/overview and legal-and-compliance):
agents built on the Agent SDK use API-key authentication (Claude Console key or a supported cloud provider),
not claude.ai / Claude Code subscription login. Enforced here, not just documented:
  * no ANTHROPIC_API_KEY -> LLMUnavailable BEFORE anything is spawned (status AUTH_BLOCKED_NO_API_KEY);
  * the CLI runs with --bare ("Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper", OAuth and
    keychain never read) and an EMPTY per-run CLAUDE_CONFIG_DIR, so a stored Claude Code login is unreachable;
  * other credential variables (OAuth token, auth token, profiles, cloud-provider switches) are blanked.
Least privilege: --tools "" (no built-in tools), explicit deny list, permission_mode dontAsk, a deny-all
PreToolUse hook that also records any attempt, setting_sources=[] (no ~/.claude or project settings), no MCP,
cwd = a per-run sandbox holding only facts.json / schema.json / prompt_meta.json (never the project root).
The provider only returns text; LLMClient does JSON / pydantic validation, grounding, retries, logging and
replay exactly as for every other provider, and any failure falls back to the template narrative.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from agent.config import ROOT
from agent.llm.base import (LLMFormatError, LLMProvider, LLMRateLimited, LLMRawResponse, LLMRequest,
                            LLMServerError, LLMTimeout, LLMUnavailable)
from agent.llm.env import get_key

BUILTIN_TOOLS = ["Bash", "BashOutput", "KillBash", "KillShell", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
                 "NotebookRead", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "Task", "Agent", "TodoWrite",
                 "TodoRead", "ExitPlanMode", "EnterPlanMode", "AskUserQuestion", "SlashCommand", "Skill",
                 "PowerShell", "Monitor", "ListMcpResourcesTool", "ReadMcpResourceTool", "mcp__*"]
BLANK_ENV = ["ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID",
             "ANTHROPIC_ORGANIZATION_ID", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
             "CLAUDE_CODE_USE_FOUNDRY", "ANTHROPIC_BASE_URL", "CLAUDECODE"]
TASK_SCHEMAS = {"market_narrator": "NarrativeOut", "thesis_writer": "ThesisOut", "reviewer": "ReviewOut",
                "event_extractor": "EventsOut"}


def sdk_version() -> str | None:
    try:
        import claude_agent_sdk
        return claude_agent_sdk.__version__
    except Exception:  # noqa: BLE001
        return None


def resolve_cli(cfg_path: str | None = "auto") -> str | None:
    """Native claude executable. The SDK refuses Windows .cmd shims (npm install), so look for the native
    claude.exe inside the npm package next to the shim."""
    if cfg_path and cfg_path != "auto":
        return cfg_path if Path(cfg_path).exists() else None
    hit = shutil.which("claude")
    if not hit:
        return None
    p = Path(hit)
    if p.suffix.lower() in (".cmd", ".bat", "") and os.name == "nt":
        native = p.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        return str(native) if native.exists() else None
    return str(p)


_CLI_VERSION: dict[str, str | None] = {}


def cli_version(cli: str | None) -> str | None:
    if not cli:
        return None
    if cli not in _CLI_VERSION:
        try:
            r = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=30)
            _CLI_VERSION[cli] = (r.stdout or "").strip().split()[0] if r.returncode == 0 else None
        except Exception:  # noqa: BLE001
            _CLI_VERSION[cli] = None
    return _CLI_VERSION[cli]


def auth_mode() -> str:
    """API_KEY when ANTHROPIC_API_KEY is configured; otherwise NONE (subscription login is never used)."""
    return "API_KEY" if get_key("ANTHROPIC_API_KEY") else "NONE"


def task_schema(task: str) -> dict | None:
    name = TASK_SCHEMAS.get(task)
    if not name:
        return None
    from agent.llm import schemas
    return getattr(schemas, name).model_json_schema()


def _sha(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


class ClaudeAgentSDKProvider(LLMProvider):
    name = "claude_agent_sdk"

    def __init__(self, model: str | None = None, cfg: dict | None = None, query_fn=None):
        self.cfg = dict(cfg or {})
        self.sdk_cfg = dict(self.cfg.get("claude_agent_sdk") or {})
        self.model = model or self.cfg.get("model") or ""
        self._query_fn = query_fn                      # tests inject a fake async generator here
        self.cli = resolve_cli(self.sdk_cfg.get("cli_path", "auto"))
        guard = self.cfg.get("prompt_guard") or "claude_agent_narrative_v1"
        from agent.llm.client import load_prompt
        self.guard_system, _, self.guard_version = load_prompt(guard)
        self.last_meta: dict = {}

    # ------------------------------------------------------------------ status
    def available(self) -> bool:
        return bool(sdk_version()) and bool(self.cli or self._query_fn) and auth_mode() == "API_KEY"

    def status(self) -> dict:
        return {"sdk_installed": bool(sdk_version()), "sdk_version": sdk_version(), "cli_path_found": bool(self.cli),
                "cli_version": cli_version(self.cli), "auth_mode": auth_mode(),
                "auth_available": auth_mode() == "API_KEY",
                "status": "READY" if self.available() else
                ("AUTH_BLOCKED_NO_API_KEY" if auth_mode() != "API_KEY" else "SDK_OR_CLI_MISSING")}

    # ------------------------------------------------------------------ sandbox / options
    def make_sandbox(self, req: LLMRequest, schema: dict | None) -> Path:
        base = Path(self.sdk_cfg.get("working_dir") or "runtime/claude_agent_sdk")
        base = base if base.is_absolute() else ROOT / base
        sb = base / f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        (sb / ".cfg").mkdir(parents=True)                # empty CLAUDE_CONFIG_DIR: no stored login reachable
        (sb / "facts.json").write_text(req.prompt, encoding="utf-8")
        (sb / "schema.json").write_text(json.dumps(schema or {}, ensure_ascii=False, indent=1), encoding="utf-8")
        (sb / "prompt_meta.json").write_text(json.dumps({"task": req.task, "prompt_version": req.prompt_version,
                                                         "guard_version": self.guard_version,
                                                         "input_hash": _sha(req.prompt)}, indent=1), encoding="utf-8")
        return sb

    def build_options(self, req: LLMRequest, sandbox: Path, schema: dict | None, key: str, tool_log: list):
        from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

        async def deny_all(hook_input, tool_use_id, context):   # defence in depth: no tool may ever run
            tool_log.append({"tool": (hook_input or {}).get("tool_name"), "tool_use_id": tool_use_id})
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": "Narrative Agent has no tools"}}
        env = {k: "" for k in BLANK_ENV}
        env.update({"ANTHROPIC_API_KEY": key, "CLAUDE_CONFIG_DIR": str(sandbox / ".cfg"),
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1"})
        extra = {"no-session-persistence": None}          # no transcript written to disk
        if self.sdk_cfg.get("bare", True):
            extra["bare"] = None
        budget = self.cfg.get("max_cost_per_day_usd")
        return ClaudeAgentOptions(
            tools=[], allowed_tools=[], disallowed_tools=list(BUILTIN_TOOLS), permission_mode="dontAsk",
            setting_sources=[], mcp_servers={}, strict_mcp_config=True, skills=None, plugins=[], agents=None,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[deny_all])]},
            system_prompt=self.guard_system + "\n\n" + req.system, cwd=str(sandbox), add_dirs=[],
            model=self.model or None, max_turns=int(self.cfg.get("max_turns", 3)),
            max_budget_usd=float(budget) if budget else None,
            output_format={"type": "json_schema", "schema": schema} if schema else None,
            cli_path=self.cli, env=env, extra_args=extra, include_partial_messages=False)

    # ------------------------------------------------------------------ call
    def complete(self, req: LLMRequest) -> LLMRawResponse:
        key = get_key("ANTHROPIC_API_KEY")
        if not key:
            raise LLMUnavailable("AUTH_BLOCKED_NO_API_KEY: the Agent SDK provider runs only with ANTHROPIC_API_KEY "
                                 "(Claude Code subscription login is never used)")
        if not sdk_version() and self._query_fn is None:
            raise LLMUnavailable("claude-agent-sdk not installed")
        if not self.cli and self._query_fn is None:
            raise LLMUnavailable("native Claude Code CLI not found (set claude_agent_sdk.cli_path)")
        schema = task_schema(req.task) if req.json_mode else None
        sandbox = self.make_sandbox(req, schema)
        tool_log: list = []
        t0 = time.perf_counter()
        try:
            out = self._run(req, sandbox, schema, key, tool_log)
        finally:
            if not self.sdk_cfg.get("keep_sandbox", False):
                remove_sandbox(sandbox)
        out.latency_sec = time.perf_counter() - t0
        return out

    def _run(self, req, sandbox, schema, key, tool_log) -> LLMRawResponse:
        import anyio
        options = self.build_options(req, sandbox, schema, key, tool_log)
        query_fn = self._query_fn
        if query_fn is None:
            from claude_agent_sdk import query as query_fn
        state: dict = {"result": None, "tool_uses": []}

        async def go():
            from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock
            with anyio.fail_after(float(req.timeout)):
                async for m in query_fn(prompt=req.prompt, options=options):
                    if isinstance(m, AssistantMessage):
                        state["tool_uses"] += [b.name for b in m.content if isinstance(b, ToolUseBlock)]
                    elif isinstance(m, ResultMessage):
                        state["result"] = m
        try:
            anyio.run(go)
        except TimeoutError as e:
            raise LLMTimeout(f"claude_agent_sdk timed out after {req.timeout}s") from e
        except LLMUnavailable:
            raise
        except Exception as e:  # noqa: BLE001
            raise map_sdk_error(e) from e
        r = state["result"]
        if r is None:
            raise LLMServerError("claude_agent_sdk: no result message")
        violations = state["tool_uses"] + [t["tool"] for t in tool_log] + list(r.permission_denials or [])
        if violations:                                  # a narrative that tried to use tools is rejected outright
            raise LLMFormatError(f"TOOL_VIOLATION: {violations[:5]}")
        if r.is_error or r.subtype != "success":
            status = getattr(r, "api_error_status", None)
            if status == 429:
                raise LLMRateLimited(f"claude_agent_sdk 429 ({r.subtype})")
            if status in (401, 403):
                raise LLMUnavailable(f"claude_agent_sdk auth error {status}")
            if r.subtype == "error_max_structured_output_retries":
                raise LLMFormatError("claude_agent_sdk: structured output retries exhausted")
            raise LLMServerError(f"claude_agent_sdk error {r.subtype} {status or ''} {(r.errors or [])[:2]}")
        if schema is not None:
            if r.structured_output is None:
                raise LLMFormatError("claude_agent_sdk: success without structured_output")
            text = json.dumps(r.structured_output, ensure_ascii=False)
        else:
            text = r.result or ""
        usage = r.usage or {}
        models = list((r.model_usage or {}).keys())
        meta = {"sdk_version": sdk_version(), "cli_version": cli_version(self.cli), "auth_mode": "API_KEY",
                "guard_version": self.guard_version, "input_hash": _sha(req.prompt), "session_id": r.session_id,
                "num_turns": r.num_turns, "duration_ms": r.duration_ms, "duration_api_ms": r.duration_api_ms,
                "total_cost_usd": r.total_cost_usd, "usage": usage,
                "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                "structured_output_native": schema is not None, "tool_violations": 0}
        self.last_meta = meta
        return LLMRawResponse(text, models[0] if models else (self.model or "claude-agent-sdk-default"),
                              usage.get("input_tokens"), usage.get("output_tokens"), 0.0, meta)


def remove_sandbox(sb: Path, attempts: int = 20, wait: float = 0.25) -> bool:
    """Windows: the CLI may still hold files for a moment after exit -> retry instead of silently leaving them."""
    for _ in range(attempts):
        shutil.rmtree(sb, ignore_errors=True)
        if not sb.exists():
            return True
        time.sleep(wait)
    return not sb.exists()


def map_sdk_error(e: Exception) -> Exception:
    """SDK / CLI failures -> the project's LLM error types (LLMClient then falls back to the template)."""
    try:
        from claude_agent_sdk import CLIConnectionError, CLIJSONDecodeError, CLINotFoundError, ProcessError
    except Exception:  # noqa: BLE001
        return LLMServerError(f"claude_agent_sdk: {type(e).__name__}: {str(e)[:200]}")
    if isinstance(e, CLINotFoundError):
        return LLMUnavailable(f"claude CLI not found: {str(e)[:200]}")
    if isinstance(e, CLIJSONDecodeError):
        return LLMFormatError(f"claude_agent_sdk JSON decode: {str(e)[:200]}")
    status = getattr(e, "api_error_status", None) or (getattr(e, "data", None) or {}).get("api_error_status")
    if status == 429:
        return LLMRateLimited("claude_agent_sdk 429")
    if status in (401, 403):
        return LLMUnavailable(f"claude_agent_sdk auth error {status}")
    msg = str(e)
    if isinstance(e, ProcessError) and any(s in msg for s in ("API key", "api key", "/login", "Not logged in",
                                                                "authentication", "x-api-key")):
        return LLMUnavailable(f"claude_agent_sdk auth: {msg[:200]}")
    if isinstance(e, (ProcessError, CLIConnectionError)):
        return LLMServerError(f"claude_agent_sdk process: {msg[:200]}")
    return LLMServerError(f"claude_agent_sdk: {type(e).__name__}: {msg[:200]}")
