"""Round 06B: ClaudeCodeCLIProvider. No real Claude call in tests: a fake runner emits official-format
stream-json lines. The process-cleanup test spawns a real (python) sleeper to exercise the hard timeout."""
import copy
import json
import sys
from pathlib import Path

import pytest

from agent.llm.base import (LLMFormatError, LLMRateLimited, LLMRequest, LLMServerError, LLMTimeout,
                            LLMUnavailable)
from agent.llm.client import load_llm_config, make_provider
from agent.llm.providers import claude_cli as C
from agent.llm.providers.claude_cli import CLIError, ClaudeCodeCLIProvider, default_runner, parse_stream
from agent.llm.providers.mock import MockProvider, TemplateProvider

CFG_PATH = "config/llm_claude_cli.yaml"
TITLE_TO_TASK = {"NarrativeOut": "market_narrator", "ThesisOut": "thesis_writer"}


def cfg(**over):
    c = copy.deepcopy(load_llm_config(CFG_PATH))
    c["enabled"] = True
    c.update(over)
    return c


def stream(result: dict | None, tools=("StructuredOutput",), mcp=(), assistant_tools=()):
    lines = [{"type": "system", "subtype": "init", "tools": list(tools), "mcp_servers": list(mcp),
              "model": "claude-test", "session_id": "s1"}]
    for t in assistant_tools:
        lines.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": t, "input": {}}]}})
    if result is not None:
        lines.append(dict({"type": "result", "subtype": "success", "is_error": False, "session_id": "s1",
                           "usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0.01,
                           "permission_denials": []}, **result))
    return "\n".join(json.dumps(x) for x in lines) + "\n"


def runner(stdout="", stderr="", exit_code=0, timed_out=False, seen=None):
    def run(cmd, stdin_text, cwd, env, timeout):
        if seen is not None:
            seen.append({"cmd": cmd, "stdin": stdin_text, "cwd": cwd, "env": env,
                         "files": sorted(p.name for p in Path(cwd).iterdir())})
        return {"pid": 1234, "start": 0, "stop": 1, "elapsed": 1.0, "timed_out": timed_out,
                "cleanup": "terminated" if timed_out else "not_needed", "exit_code": None if timed_out else exit_code,
                "stdout": stdout, "stderr": stderr}
    return run


def mock_runner(mode="normal"):
    """Answers like the CLI would, with the deterministic MockProvider (grounded by construction)."""
    mock = MockProvider("mock-rules-v1", mode)

    def run(cmd, stdin_text, cwd, env, timeout):
        schema = json.loads(cmd[cmd.index("--json-schema") + 1]) if "--json-schema" in cmd else {}
        task = TITLE_TO_TASK.get(schema.get("title"), "market_narrator")
        system = (Path(cwd) / "system_prompt.txt").read_text(encoding="utf-8")
        text = mock.complete(LLMRequest(task=task, system=system, prompt=stdin_text, prompt_version="t")).text
        return {"pid": 1, "elapsed": 0.5, "timed_out": False, "cleanup": "not_needed", "exit_code": 0,
                "stdout": stream({"structured_output": json.loads(text)}), "stderr": ""}
    return run


def req(task="market_narrator", timeout=5.0):
    return LLMRequest(task=task, system="sys", prompt='<INPUT_JSON>{"facts":{"F1":{"statement":"x"}}}</INPUT_JSON>',
                      prompt_version="t", timeout=timeout)


@pytest.fixture(autouse=True)
def sandbox_root(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ROOT", tmp_path)


GOOD = {"structured_output": {"logic": "台股二十日趨勢為正（F1），量化維持持有。", "counter_evidence": None, "fact_refs": ["F1"]}}


# ------------------------------------------------------------------ resolution / auth
def test_resolver_prefers_verified_native_and_rejects_unknown(monkeypatch):
    monkeypatch.setattr(C, "_candidates", lambda: [("C:/x/fake/claude.exe", "native"), ("C:/y/claude.exe", "path_exe")])
    monkeypatch.setattr(C, "_version_of", lambda p: None if "fake" in p else "2.1.289")
    r = C.resolve_claude_cli(refresh=True)
    assert r["path"] == "C:/y/claude.exe" and r["rejected"] == ["native"] and r["version"] == "2.1.289"
    monkeypatch.setattr(C, "_version_of", lambda p: None)
    assert C.resolve_claude_cli(refresh=True)["path"] is None
    C._RESOLVED = None


def test_version_regex():
    assert C.VERSION_RE.match("2.1.289 (Claude Code)") and not C.VERSION_RE.match("claude 1.0 (Other Tool)")


def test_auth_probe_parse_whitelists_fields():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "experiments" / "claude_cli_runtime"))
    from auth_probe import parse_status
    raw = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "team", "email": "a@b.c",
                      "orgId": "org-123", "orgName": "Some Org", "configDirectory": "C:/x"})
    out = parse_status(raw, 0)
    assert out["loggedIn"] and out["authMethod"] == "claude.ai" and out["ORG_MANAGED_ACCOUNT"] is True
    dumped = json.dumps(out)
    assert "a@b.c" not in dumped and "org-123" not in dumped and "Some Org" not in dumped and "C:/x" not in dumped
    assert parse_status("not json", 1)["authMethod"] == "unparseable"


def test_clean_env_drops_parent_session_and_api_vars(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    e = C.clean_env()
    assert "CLAUDECODE" not in e and "CLAUDE_CODE_ENTRYPOINT" not in e and "ANTHROPIC_API_KEY" not in e
    assert e["CLAUDE_CODE_SKIP_PROMPT_HISTORY"] == "1"


def test_disabled_config_is_template():
    assert isinstance(make_provider(load_llm_config(CFG_PATH)), TemplateProvider)


# ------------------------------------------------------------------ command line / stdin / sandbox
def test_command_is_locked_and_prompt_goes_to_stdin():
    seen = []
    p = ClaudeCodeCLIProvider(None, cfg(), runner=runner(stream(GOOD), seen=seen))
    r = req()
    p.complete(r)
    cmd, s = seen[0]["cmd"], seen[0]
    assert cmd[1] == "-p" and cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert cmd[cmd.index("--tools") + 1] == "" and cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert {"Bash", "PowerShell", "Read", "Write", "Edit", "WebFetch", "mcp__*"} <= set(cmd[cmd.index("--disallowedTools") + 1].split(","))
    for f in ("--restricted", "--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--json-schema"):
        assert f in cmd
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    for bad in ("--dangerously-skip-permissions", "bypassPermissions", "--continue", "--resume"):
        assert bad not in cmd
    assert s["stdin"] == r.prompt and r.prompt not in " ".join(cmd)                # prompt only on stdin
    assert s["files"] == ["facts.json", "prompt_meta.json", "schema.json", "system_prompt.txt"]
    assert Path(s["cwd"]) != C.ROOT and Path(cmd[cmd.index("--system-prompt-file") + 1]).parent == Path(s["cwd"])
    assert not Path(s["cwd"]).exists()                                              # sandbox removed afterwards


def test_research_profile_only_adds_read():
    p = ClaudeCodeCLIProvider(None, cfg(), runner=runner(), profile="RESEARCH_READONLY")
    cmd = p.build_cmd(Path("x"), None)
    assert cmd[cmd.index("--tools") + 1] == "Read" and "Read" not in cmd[cmd.index("--disallowedTools") + 1].split(",")
    assert {"Write", "Edit", "Bash", "WebFetch", "mcp__*"} <= set(cmd[cmd.index("--disallowedTools") + 1].split(","))
    with pytest.raises(ValueError):
        ClaudeCodeCLIProvider(None, cfg(), runner=runner(), profile="FULL_ACCESS")


def test_windows_chinese_path_sandbox(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "ROOT", tmp_path / "個人" / "玉山挑戰賽")
    seen = []
    ClaudeCodeCLIProvider(None, cfg(), runner=runner(stream(GOOD), seen=seen)).complete(req())
    assert "個人" in seen[0]["cwd"]


# ------------------------------------------------------------------ parsing / errors
def test_json_output_parsed_with_metadata():
    p = ClaudeCodeCLIProvider(None, cfg(), runner=runner(stream(GOOD)))
    r = p.complete(req())
    assert json.loads(r.text)["fact_refs"] == ["F1"] and r.model_version == "claude-test"
    m = r.provider_meta
    assert m["exit_code"] == 0 and m["init_tools"] == ["StructuredOutput"] and m["tool_violations"] == 0
    assert m["output_hash"].startswith("sha256:") and m["input_hash"].startswith("sha256:")


@pytest.mark.parametrize("kw,exc,cat", [
    (dict(stdout=stream({"subtype": "error_during_execution", "is_error": True, "result": "Not logged in · Please run /login"}), exit_code=1), LLMUnavailable, "NOT_AUTHENTICATED"),
    (dict(stdout=stream({"subtype": "error_during_execution", "is_error": True, "result": "Claude usage limit reached. Your limit resets at 5pm"}), exit_code=1), LLMUnavailable, "USAGE_LIMIT"),
    (dict(stdout=stream({"subtype": "error_during_execution", "is_error": True, "api_error_status": 429, "result": "rate_limit"}), exit_code=1), LLMRateLimited, "RATE_LIMIT"),
    (dict(stdout=stream({"subtype": "error_during_execution", "is_error": True, "result": "model_not_found: claude-x"}), exit_code=1), LLMUnavailable, "MODEL_UNAVAILABLE"),
    (dict(stdout=stream({"subtype": "error_max_structured_output_retries", "is_error": True}), exit_code=1), LLMFormatError, "SCHEMA_FAIL"),
    (dict(stdout=stream({"structured_output": None})), LLMFormatError, "SCHEMA_FAIL"),
    (dict(stdout="garbage not json\n", exit_code=1), LLMFormatError, "INVALID_JSON"),
    (dict(stdout=stream({"subtype": "error_during_execution", "is_error": True, "result": "boom"}), exit_code=3), LLMServerError, "NONZERO_EXIT"),
    (dict(timed_out=True), LLMTimeout, "TIMEOUT"),
    (dict(stdout=stream(GOOD, assistant_tools=["Bash"])), LLMFormatError, "TOOL_VIOLATION"),
    (dict(stdout=stream(GOOD, tools=["StructuredOutput", "Read"])), LLMFormatError, "TOOL_VIOLATION"),
    (dict(stdout=stream(GOOD, mcp=[{"name": "x", "status": "connected"}])), LLMFormatError, "TOOL_VIOLATION"),
    (dict(stdout=stream(dict(GOOD, permission_denials=[{"tool_name": "Write"}]))), LLMFormatError, "TOOL_VIOLATION"),
])
def test_error_classification(kw, exc, cat):
    p = ClaudeCodeCLIProvider(None, cfg(), runner=runner(**kw))
    with pytest.raises(exc) as ei:
        p.complete(req())
    assert ei.value.category == cat


def test_unavailable_paths_never_spawn(monkeypatch):
    called = []
    p = ClaudeCodeCLIProvider(None, cfg(), runner=lambda *a: called.append(1))
    p._cli = {"path": None, "kind": None, "version": None}
    with pytest.raises(LLMUnavailable, match="CLI_NOT_FOUND"):
        p.complete(req())
    p._cli = {"path": "claude", "kind": "test", "version": "x"}
    p._auth = {"loggedIn": False}
    with pytest.raises(LLMUnavailable, match="NOT_AUTHENTICATED"):
        p.complete(req())
    assert called == []


def test_usage_limit_is_not_retried(tmp_path):
    """USAGE_LIMIT maps to LLMUnavailable (never retried): exactly one CLI call, then template."""
    from agent.llm.client import LLMClient
    from agent.llm.logging import LLMCallLogger
    from agent.llm.schemas import NarrativeOut
    n = []
    base = runner(stdout=stream({"subtype": "error_during_execution", "is_error": True,
                                 "result": "Claude usage limit reached"}), exit_code=1)

    def counting(*a):
        n.append(1)
        return base(*a)
    c = LLMClient(cfg(retries=3), ClaudeCodeCLIProvider(None, cfg(), runner=counting),
                  LLMCallLogger(root=tmp_path, run_date="2026-10-05"))
    assert c.generate_structured(c.request("market_narrator", "market_narrator_v1", {"facts": {}}), NarrativeOut) is None
    assert len(n) == 1


def test_stderr_is_redacted():
    s = C.redact_stderr("error token=abcd1234secret key: " + "x" * 40 + " Authorization: Bearer zzz")
    assert "abcd1234secret" not in s and "x" * 40 not in s


def test_parse_stream_ignores_structured_output_tool():
    ps = parse_stream(stream(GOOD, assistant_tools=["StructuredOutput"]))
    assert ps["tool_uses"] == [] and ps["result"]["subtype"] == "success"


# ------------------------------------------------------------------ real process timeout / cleanup
def test_hard_timeout_terminates_and_leaves_no_process(tmp_path):
    import subprocess
    cmd = [sys.executable, "-c", "import time; time.sleep(60)"]
    rec = default_runner(cmd, "", str(tmp_path), C.clean_env(), timeout=1.0, grace=2.0)
    assert rec["timed_out"] and rec["cleanup"] in ("terminated", "killed_tree") and rec["elapsed"] < 30
    out = subprocess.run(["tasklist", "/FI", f"PID eq {rec['pid']}", "/NH"], capture_output=True, text=True).stdout
    assert str(rec["pid"]) not in out


# ------------------------------------------------------------------ grounding / pipeline
@pytest.mark.parametrize("logic,ok", [("台股趨勢為正（F1），本日無委託。", True),
                                     ("營收年增 +15%（F1），建議加碼。", False),
                                     ("將 2330 權重設為 25% 並下單。", False)])
def test_numeric_ticker_and_instruction_grounding(tmp_path, logic, ok):
    from agent.llm.client import LLMClient
    from agent.llm.grounding import allowed_numbers, bad_refs, ungrounded_numbers
    from agent.llm.logging import LLMCallLogger
    from agent.llm.schemas import NarrativeOut
    from agent.research.reviewer import FORBIDDEN
    payload = {"facts": {"F1": {"statement": "TAIEX 20-day trend positive"}}}
    p = ClaudeCodeCLIProvider(None, cfg(), runner=runner(stream({"structured_output": {"logic": logic + "。" * 10,
                                                                                         "fact_refs": ["F1"]}})))
    c = LLMClient(cfg(), p, LLMCallLogger(root=tmp_path, run_date="2026-10-05"))

    def validator(o):
        bad = bad_refs(o.fact_refs, {"F1"}) + ungrounded_numbers(o.logic, allowed_numbers(payload))
        return bad + (["forbidden"] if FORBIDDEN.search(o.logic) else [])
    out = c.generate_structured(c.request("market_narrator", "market_narrator_v1", payload, ["F1"]), NarrativeOut, validator)
    assert (out is not None) == ok


def _pair(fixture_store, rb, tmp_path, provider, c=None):
    import yaml
    from agent.config import load_strategy
    from agent.pipeline import llm_settings, run_day
    from agent.sim.calendar import TradingCalendar
    from agent.sim.models import Settlement
    strat = load_strategy("config/strategy_quant_v1.yaml")
    cal = TradingCalendar(fixture_store.dates())
    s0 = Settlement.initial(cal.prev("2026-10-26"), rb.rules.initial_cash)
    t = run_day("2026-10-26", fixture_store, copy.deepcopy(s0), rb, strat, team_id="TEAM_TEST", out_dir=tmp_path / "t",
                log_dir=None, store_is_fixture=True, calendar=cal, light=True)
    f = tmp_path / "cli.yaml"
    f.write_text(yaml.safe_dump(c or cfg(), allow_unicode=True), encoding="utf-8")
    llm = llm_settings(strat, None, None, str(f), provider_instance=provider, log_root=tmp_path / "llmlogs")
    s = run_day("2026-10-26", fixture_store, copy.deepcopy(s0), rb, strat, team_id="TEAM_TEST", out_dir=tmp_path / "s",
                log_dir=None, store_is_fixture=True, calendar=cal, light=True, llm=llm)
    return t, s


def _same(t, s):
    from agent.ops.fingerprint import decision_core_hash
    assert t.doc["orders"] == s.doc["orders"] and t.doc["decisions"] == s.doc["decisions"]
    assert t.result.est_cash == s.result.est_cash
    assert t.active_share.minimum_active_share == s.active_share.minimum_active_share
    for k in ("regime", "stance", "posture"):
        assert t.doc["market_view"][k] == s.doc["market_view"][k]
    assert decision_core_hash(t.doc) == decision_core_hash(s.doc) and s.validation.ok


def test_cli_narrative_decision_invariance_and_replay(fixture_store, rb, tmp_path):
    from agent.llm.replay import ReplayProvider
    from agent.ops.fingerprint import narrative_text
    t, s = _pair(fixture_store, rb, tmp_path, ClaudeCodeCLIProvider(None, cfg(), runner=mock_runner()))
    _same(t, s)
    assert s.narrative_used_llm
    _, s2 = _pair(fixture_store, rb, tmp_path / "r", ReplayProvider([tmp_path / "llmlogs"]))
    assert narrative_text(s2.doc) == narrative_text(s.doc)


@pytest.mark.parametrize("kw", [dict(timed_out=True), dict(stdout="nope", exit_code=1),
                                dict(stdout=stream({"subtype": "error_during_execution", "is_error": True,
                                                    "result": "Claude usage limit reached"}), exit_code=1),
                                dict(stdout=stream(GOOD, assistant_tools=["Bash"]))])
def test_cli_failure_falls_back_to_template(fixture_store, rb, tmp_path, kw):
    t, s = _pair(fixture_store, rb, tmp_path, ClaudeCodeCLIProvider(None, cfg(), runner=runner(**kw)))
    _same(t, s)
    assert not s.narrative_used_llm


def test_session_isolation_flags():
    p = ClaudeCodeCLIProvider(None, cfg(), runner=runner())
    cmd = p.build_cmd(Path("a"), None)
    assert "--no-session-persistence" in cmd and "--continue" not in cmd and "--resume" not in cmd
    assert "--safe-mode" in cmd                     # no CLAUDE.md / auto memory
    assert "--setting-sources" in cmd and cmd[cmd.index("--setting-sources") + 1] == ""


def test_competition_day_with_cli_provider_keeps_decision(fixture_store, tmp_path):
    from agent.competition_day import run_competition_day
    from agent.ops.common import Clock, load_ops_config
    from tests.ops.conftest import CLEAN_GIT
    import copy as _copy

    def ops(sub):
        c = _copy.deepcopy(load_ops_config())
        for i, k in enumerate(c["paths"]):
            c["paths"][k] = str(tmp_path / sub / f"{k[:3]}{i}")
        return c
    kw = dict(store=fixture_store, store_is_fixture=True, clock=Clock("2026-10-25T20:00:00+08:00"), git=CLEAN_GIT,
              archive_readonly=False, skip_refresh=True, initial=True, write_report=False)
    t = run_competition_day("2026-10-26", "TEAM_TEST", "dry-run", ops_cfg=ops("t"), **kw)
    c = run_competition_day("2026-10-26", "TEAM_TEST", "dry-run", ops_cfg=ops("c"), llm_config=CFG_PATH,
                            llm_provider=ClaudeCodeCLIProvider(None, cfg(), runner=mock_runner()), **kw)
    assert t["status"] == c["status"] == "DRY_RUN_OK" and c["llm"]["used"] and c["degradation_level"] == 0
    assert t["decision_fingerprint"] == c["decision_fingerprint"]
    assert not [x for x in c["sla"] if x["metric"] == "quant_sec" and x["breach"]]
