"""ClaudeCodeCLIProvider (Round 06B PoC): the user's own, unmodified, already-logged-in Claude Code CLI in
non-interactive mode (`claude -p`) as a narrative LLM runtime. Python never touches credentials: it only runs
the official binary; authentication is entirely Claude Code's own (OAuth login / its configured method).

Locked narrative profile (NARRATIVE_LOCKED):
  -p --output-format stream-json --verbose     official JSON lines on stdout (init event lists tools / MCP servers)
  --json-schema <schema>                       native validated structured output
  --tools ""  --disallowedTools <all tools, mcp__*>   no built-in or MCP tool
  --permission-mode dontAsk --permission-prompts none  anything that would prompt is denied
  --restricted                                 no command tools, file tools confined, only managed settings load
  --safe-mode                                  no CLAUDE.md, skills, plugins, hooks, MCP servers, auto memory
  --setting-sources "" --strict-mcp-config --no-session-persistence
  --system-prompt-file <sandbox file>          replaces Claude Code's default (coding) system prompt
  prompt on stdin; cwd = runtime/claude_cli/<run_id>/ (facts, schema, prompt only; never the project root)
Never: --dangerously-skip-permissions, bypassPermissions, --continue / --resume, setup-token, API keys.
Every failure -> an LLM error -> LLMClient returns None -> Template narrative. Decisions are never touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path

from agent.config import ROOT
from agent.llm.base import (LLMFormatError, LLMProvider, LLMRateLimited, LLMRawResponse, LLMRequest,
                            LLMServerError, LLMTimeout, LLMUnavailable)

VERSION_RE = re.compile(r"^(\d+\.\d+\.\d+)\s+\(Claude Code\)")
ALL_TOOLS = ["Bash", "PowerShell", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep", "LS",
             "WebFetch", "WebSearch", "Task", "Agent", "TodoWrite", "Skill", "SlashCommand", "Monitor",
             "AskUserQuestion", "ExitPlanMode", "EnterPlanMode", "BashOutput", "KillShell", "mcp__*"]
PROFILES = {
    "NARRATIVE_LOCKED": {"tools": "", "allowed": [], "deny": ALL_TOOLS},
    "RESEARCH_READONLY": {"tools": "Read", "allowed": ["Read"], "deny": [t for t in ALL_TOOLS if t != "Read"]},
}
TASK_SCHEMAS = {"market_narrator": "NarrativeOut", "thesis_writer": "ThesisOut", "reviewer": "ReviewOut",
                "event_extractor": "EventsOut",
                "mops_research": "ResearchOut"}
CATEGORIES = ("CLI_NOT_FOUND", "NOT_AUTHENTICATED", "TIMEOUT", "NONZERO_EXIT", "INVALID_JSON", "SCHEMA_FAIL",
              "GROUNDING_FAIL", "TOOL_VIOLATION", "RATE_LIMIT", "USAGE_LIMIT", "MODEL_UNAVAILABLE", "UNKNOWN_CLI_ERROR")


# ----------------------------------------------------------------------------- binary resolution
def _version_of(path: str) -> str | None:
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30, env=clean_env(),
                           encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None
    m = VERSION_RE.match((r.stdout or "").strip())
    return m.group(1) if (r.returncode == 0 and m) else None


def _candidates() -> list[tuple[str, str]]:
    """(path, kind). Native executables first; never a hard-coded user name."""
    out: list[tuple[str, str]] = []
    home = Path.home()
    native = [home / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")]   # official native installer
    appdata = os.environ.get("APPDATA")
    if appdata:
        native.append(Path(appdata) / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe")
    hits: list[str] = []
    if os.name == "nt":
        try:
            r = subprocess.run(["where.exe", "claude"], capture_output=True, text=True, timeout=15)
            hits = [h.strip() for h in r.stdout.splitlines() if h.strip()]
        except Exception:  # noqa: BLE001
            hits = []
    elif shutil.which("claude"):
        hits = [shutil.which("claude")]
    for h in hits:                                   # npm shim -> its bundled native exe
        p = Path(h)
        sib = p.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if sib not in native:
            native.append(sib)
    for p in native:
        if p.exists():
            out.append((str(p), "native"))
    for h in hits:                                   # fallback: an .exe found on PATH
        if h.lower().endswith(".exe") and h not in [c for c, _ in out]:
            out.append((h, "path_exe"))
    return out


_RESOLVED: dict | None = None


def resolve_claude_cli(refresh: bool = False) -> dict:
    """First candidate whose `--version` really answers 'x.y.z (Claude Code)'. Unknown binaries are rejected."""
    global _RESOLVED
    if _RESOLVED is not None and not refresh:
        return _RESOLVED
    rejected = []
    for path, kind in _candidates():
        v = _version_of(path)
        if v:
            _RESOLVED = {"path": path, "kind": kind, "version": v, "rejected": rejected}
            return _RESOLVED
        rejected.append(kind)
    _RESOLVED = {"path": None, "kind": None, "version": None, "rejected": rejected}
    return _RESOLVED


def clean_env() -> dict:
    """Environment for the child: drop markers of a parent Claude Code session (nested-session state) and any
    API credential variables, so the CLI authenticates exactly as the user's own CLI does."""
    drop_prefix = ("CLAUDE_CODE_", "CLAUDECODE", "ANTHROPIC_")
    env = {k: v for k, v in os.environ.items() if not k.startswith(drop_prefix)}
    env["CLAUDE_CODE_SKIP_PROMPT_HISTORY"] = "1"
    return env


def auth_status() -> dict:
    """Whitelisted `claude auth status` fields (never tokens / emails / org names)."""
    cli = resolve_claude_cli()
    if not cli["path"]:
        return {"loggedIn": False, "authMethod": "none", "error": "CLI_NOT_FOUND"}
    try:
        r = subprocess.run([cli["path"], "auth", "status"], capture_output=True, text=True, timeout=60,
                           env=clean_env(), encoding="utf-8", errors="replace")
        j = json.loads(r.stdout or "{}")
    except Exception as e:  # noqa: BLE001
        return {"loggedIn": False, "authMethod": "unknown", "error": type(e).__name__}
    # Round 07: exactly four whitelisted fields; nothing else from the status JSON is read or kept
    return {"loggedIn": bool(j.get("loggedIn", r.returncode == 0)), "authMethod": j.get("authMethod"),
            "subscriptionType": j.get("subscriptionType"), "apiProvider": j.get("apiProvider")}


def version_check(version: str | None, supported: list[str] | None) -> str:
    """Version pin: VERSION_VALIDATED | WARNING_VERSION_DRIFT (never a block) | CLI_NOT_FOUND."""
    if not version:
        return "CLI_NOT_FOUND"
    if not supported or version in [str(v) for v in supported]:
        return "VERSION_VALIDATED"
    return "WARNING_VERSION_DRIFT"


def _sha(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


def task_schema(task: str) -> dict | None:
    name = TASK_SCHEMAS.get(task)
    if not name:
        return None
    from agent.llm import schemas
    return getattr(schemas, name).model_json_schema()


def redact_stderr(s: str, limit: int = 240) -> str:
    s = re.sub(r"(?i)(token|key|secret|cookie|authorization)\S*\s*[:=]\s*\S+", r"\1=[redacted]", s or "")
    s = re.sub(r"[A-Za-z0-9_\-]{32,}", "[redacted]", s)
    return " ".join(s.split())[:limit]


class CLIError:
    """Error classification of one CLI run -> project LLM error types."""

    @staticmethod
    def classify(exit_code: int | None, result: dict | None, stderr: str) -> str:
        text = " ".join(str(x) for x in ((result or {}).get("result"), (result or {}).get("errors"), stderr) if x)
        low = text.lower()
        status = (result or {}).get("api_error_status")
        if "not logged in" in low or "/login" in low or "authentication_failed" in low or status in (401, 403):
            return "NOT_AUTHENTICATED"
        if "usage limit" in low or "limit reached" in low or "out of extra usage" in low or "weekly limit" in low:
            return "USAGE_LIMIT"
        if status == 429 or "rate_limit" in low or "rate limit" in low or "overloaded" in low or status == 529:
            return "RATE_LIMIT"
        if "model_not_found" in low or "not_found_error" in low or ("model" in low and "not found" in low):
            return "MODEL_UNAVAILABLE"
        if (result or {}).get("subtype") == "error_max_structured_output_retries":
            return "SCHEMA_FAIL"
        if exit_code not in (0, None):
            return "NONZERO_EXIT"
        return "UNKNOWN_CLI_ERROR"

    @staticmethod
    def to_exception(cat: str, detail: str) -> Exception:
        cls = {"CLI_NOT_FOUND": LLMUnavailable, "NOT_AUTHENTICATED": LLMUnavailable, "USAGE_LIMIT": LLMUnavailable,
               "MODEL_UNAVAILABLE": LLMUnavailable, "TIMEOUT": LLMTimeout, "RATE_LIMIT": LLMRateLimited,
               "INVALID_JSON": LLMFormatError, "SCHEMA_FAIL": LLMFormatError, "TOOL_VIOLATION": LLMFormatError,
               "GROUNDING_FAIL": LLMFormatError}.get(cat, LLMServerError)
        e = cls(f"{cat}: {detail}"[:400])
        e.category = cat
        return e


def default_runner(cmd: list[str], stdin_text: str, cwd: str, env: dict, timeout: float, grace: float = 5.0) -> dict:
    """Hard-timeout subprocess. Timeout: terminate -> grace -> kill the process tree only if needed."""
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    t0 = time.time()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env,
                         creationflags=flags, start_new_session=os.name != "nt")
    rec = {"pid": p.pid, "start": t0, "timed_out": False, "cleanup": "not_needed"}
    try:
        out, err = p.communicate(stdin_text.encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired:
        rec["timed_out"] = True
        try:
            if os.name == "nt":
                p.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                p.terminate()
            out, err = p.communicate(timeout=grace)
            rec["cleanup"] = "terminated"
        except Exception:  # noqa: BLE001
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=30)
            else:
                os.killpg(p.pid, signal.SIGKILL)
            out, err = p.communicate(timeout=30)
            rec["cleanup"] = "killed_tree"
    rec.update(stop=time.time(), exit_code=p.returncode, stdout=out.decode("utf-8", "replace"),
               stderr=err.decode("utf-8", "replace"))
    rec["elapsed"] = rec["stop"] - t0
    return rec


def parse_stream(stdout: str) -> dict:
    """Official stream-json lines -> {init, result, tool_uses, lines}. Non-JSON lines => INVALID_JSON."""
    init, result, tool_uses, bad = None, None, [], 0
    for line in (stdout or "").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            init = ev
        elif ev.get("type") == "assistant":
            for b in (ev.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") != "StructuredOutput":
                    tool_uses.append(b.get("name"))
        elif ev.get("type") == "result":
            result = ev
    return {"init": init, "result": result, "tool_uses": tool_uses, "bad_lines": bad}


class ClaudeCodeCLIProvider(LLMProvider):
    name = "claude_cli"

    def __init__(self, model: str | None = None, cfg: dict | None = None, runner=None, profile: str | None = None):
        self.cfg = dict(cfg or {})
        self.cli_cfg = dict(self.cfg.get("claude_cli") or {})
        self.model = model or self.cfg.get("model") or ""
        self.profile = profile or self.cli_cfg.get("profile", "NARRATIVE_LOCKED")
        if self.profile not in PROFILES:
            raise ValueError(f"unknown profile {self.profile}")
        self.runner = runner or default_runner
        self._cli = None if runner is None else {"path": "claude", "kind": "test", "version": "0.0.0-test"}
        from agent.llm.client import load_prompt
        self.guard_system, _, self.guard_version = load_prompt(self.cfg.get("prompt_guard") or "claude_cli_narrative_v1")
        self._auth: dict | None = None
        self.last_meta: dict = {}
        self.extra_files: dict[str, str] = {}           # RESEARCH_READONLY: files copied into the sandbox
        self.schema_overrides: dict[str, dict] = {}     # experiments: task -> JSON schema

    # ------------------------------------------------------------------ status
    @property
    def cli(self) -> dict:
        if self._cli is None:
            self._cli = resolve_claude_cli()
        return self._cli

    def auth(self) -> dict:
        if self._auth is None:
            self._auth = {"loggedIn": True, "authMethod": "test"} if self.runner is not default_runner else auth_status()
        return self._auth

    def available(self) -> bool:
        a = self.auth()
        accepted = self.cfg.get("accepted_auth_methods") or ["claude.ai"]
        return bool(self.cli["path"]) and bool(a.get("loggedIn")) and (
            self.runner is not default_runner or a.get("authMethod") in accepted)

    def healthcheck(self) -> dict:
        """READY = CLI found + logged in with an accepted method; anything else = DEGRADED (template fallback).
        Version drift is only a warning. Never blocks the quant run."""
        a = self.auth()
        ok = self.available()
        return {"cli_found": bool(self.cli["path"]), "cli_kind": self.cli["kind"], "claude_code_version": self.cli["version"],
                "version_check": version_check(self.cli["version"], self.cfg.get("supported_versions")),
                "loggedIn": a.get("loggedIn"), "authMethod": a.get("authMethod"),
                "subscriptionType": a.get("subscriptionType"), "apiProvider": a.get("apiProvider"),
                "profile": self.profile, "fallback": self.cfg.get("fallback_provider") or "template",
                "llm_status": "READY" if ok else "DEGRADED",
                "status": "READY" if ok else ("CLI_NOT_FOUND" if not self.cli["path"] else "NOT_AUTHENTICATED")}

    def provider_metadata(self) -> dict:
        return {"provider": self.name, "claude_code_version": self.cli["version"], "auth_method": self.auth().get("authMethod"),
                "model": self.model or "cli-default", "profile": self.profile, "guard_version": self.guard_version}

    # ------------------------------------------------------------------ command / sandbox
    def build_cmd(self, sandbox: Path, schema: dict | None) -> list[str]:
        prof = PROFILES[self.profile]
        cmd = [self.cli["path"], "-p", "--output-format", "stream-json", "--verbose",
               "--tools", prof["tools"], "--disallowedTools", ",".join(prof["deny"]),
               "--permission-mode", "dontAsk", "--permission-prompts", "none", "--restricted", "--safe-mode",
               "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence",
               "--system-prompt-file", str(sandbox / "system_prompt.txt"),
               "--max-turns", str(int(self.cfg.get("max_turns", 3)))]
        if prof["allowed"]:
            cmd += ["--allowedTools", ",".join(prof["allowed"])]
        if schema:
            cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False, separators=(",", ":"))]
        if self.model:
            cmd += ["--model", self.model]
        for bad in ("--dangerously-skip-permissions", "bypassPermissions", "--continue", "--resume", "-c", "-r"):
            assert bad not in cmd, bad
        return cmd

    def make_sandbox(self, req: LLMRequest, schema: dict | None) -> Path:
        base = Path(self.cli_cfg.get("working_dir") or "runtime/claude_cli")
        base = base if base.is_absolute() else ROOT / base
        sb = base / f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        sb.mkdir(parents=True)
        (sb / "system_prompt.txt").write_text(self.guard_system + "\n\n" + req.system, encoding="utf-8")
        (sb / "facts.json").write_text(req.prompt, encoding="utf-8")
        (sb / "schema.json").write_text(json.dumps(schema or {}, ensure_ascii=False, indent=1), encoding="utf-8")
        (sb / "prompt_meta.json").write_text(json.dumps({"task": req.task, "prompt_version": req.prompt_version,
                                                         "guard_version": self.guard_version,
                                                         "input_hash": _sha(req.prompt)}), encoding="utf-8")
        for name, content in self.extra_files.items():
            f = sb / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content, encoding="utf-8")
        return sb

    # ------------------------------------------------------------------ call
    def complete(self, req: LLMRequest) -> LLMRawResponse:
        if not self.cli["path"]:
            raise CLIError.to_exception("CLI_NOT_FOUND", "official claude binary not found / not verified")
        a = self.auth()
        if not a.get("loggedIn"):
            raise CLIError.to_exception("NOT_AUTHENTICATED", "claude auth status: not logged in")
        schema = (self.schema_overrides.get(req.task) or task_schema(req.task)) if req.json_mode else None
        sandbox = self.make_sandbox(req, schema)
        before = set(p.name for p in sandbox.iterdir())
        try:
            run = self.runner(self.build_cmd(sandbox, schema), req.prompt, str(sandbox), clean_env(),
                              float(req.timeout))
            created = sorted(set(p.name for p in sandbox.iterdir()) - before)
        finally:
            if not self.cli_cfg.get("keep_sandbox", False):
                remove_dir(sandbox)
        meta = {"claude_code_version": self.cli["version"], "auth_method": a.get("authMethod"), "profile": self.profile,
                "guard_version": self.guard_version, "pid": run.get("pid"), "exit_code": run.get("exit_code"),
                "elapsed_sec": round(run.get("elapsed", 0.0), 3), "timed_out": run.get("timed_out"),
                "cleanup": run.get("cleanup"), "stderr_summary": redact_stderr(run.get("stderr", "")),
                "input_hash": _sha(req.prompt), "sandbox_created_files": created}
        self.last_meta = meta
        if run.get("timed_out"):
            raise CLIError.to_exception("TIMEOUT", f"no result within {req.timeout}s (cleanup {run.get('cleanup')})")
        ps = parse_stream(run.get("stdout", ""))
        res, init = ps["result"], ps["init"] or {}
        meta.update(init_tools=init.get("tools"), init_mcp_servers=init.get("mcp_servers"), model=init.get("model"))
        if res is None:
            cat = CLIError.classify(run.get("exit_code"), None, run.get("stderr", ""))
            raise CLIError.to_exception("INVALID_JSON" if cat in ("NONZERO_EXIT", "UNKNOWN_CLI_ERROR") else cat,
                                        f"no result event (exit {run.get('exit_code')}, bad lines {ps['bad_lines']})")
        meta.update(session_id=res.get("session_id"), usage=res.get("usage"), total_cost_usd=res.get("total_cost_usd"),
                    num_turns=res.get("num_turns"), permission_denials=res.get("permission_denials"),
                    terminal_reason=res.get("terminal_reason"), duration_ms=res.get("duration_ms"))
        allowed_tools = set(PROFILES[self.profile]["allowed"]) | {"StructuredOutput"}
        exposed = [t for t in (init.get("tools") or []) if t not in allowed_tools]
        violations = ps["tool_uses"] + list(res.get("permission_denials") or []) + exposed + \
            [m for m in (init.get("mcp_servers") or [])]
        if self.profile == "RESEARCH_READONLY":
            violations = [v for v in violations if v != "Read"]
        meta["tool_violations"] = len(violations)
        if violations:
            raise CLIError.to_exception("TOOL_VIOLATION", str(violations[:5]))
        if res.get("is_error") or res.get("subtype") != "success" or run.get("exit_code") not in (0, None):
            raise CLIError.to_exception(CLIError.classify(run.get("exit_code"), res, run.get("stderr", "")),
                                        redact_stderr(str(res.get("result") or res.get("errors") or "")))
        if schema is not None:
            so = res.get("structured_output")
            if so is None:
                raise CLIError.to_exception("SCHEMA_FAIL", "success without structured_output")
            text = json.dumps(so, ensure_ascii=False)
        else:
            text = res.get("result") or ""
        meta["output_hash"] = _sha(text)
        usage = res.get("usage") or {}
        model = meta.get("model") or next(iter((res.get("modelUsage") or {}).keys()), None) or self.model or "cli-default"
        return LLMRawResponse(text, model, usage.get("input_tokens"), usage.get("output_tokens"),
                              run.get("elapsed", 0.0), meta)

    # convenience wrappers
    def generate(self, system: str, prompt: str, timeout: float = 120.0) -> str:
        return self.complete(LLMRequest(task="free_text", system=system, prompt=prompt, prompt_version="adhoc",
                                        json_mode=False, timeout=timeout)).text

    def generate_structured(self, task: str, system: str, prompt: str, timeout: float = 120.0) -> dict:
        return json.loads(self.complete(LLMRequest(task=task, system=system, prompt=prompt, prompt_version="adhoc",
                                                   timeout=timeout)).text)


def remove_dir(sb: Path, attempts: int = 20, wait: float = 0.25) -> bool:
    for _ in range(attempts):
        shutil.rmtree(sb, ignore_errors=True)
        if not sb.exists():
            return True
        time.sleep(wait)
    return not sb.exists()
