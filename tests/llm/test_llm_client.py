"""Provider abstraction, key handling, retries, budgets, logging, replay."""
import json
import os

import pytest

from agent.llm.base import LLMRequest
from agent.llm.client import LLMClient, load_llm_config, load_prompt, make_provider
from agent.llm.env import load_dotenv, redact
from agent.llm.logging import LLMCallLogger
from agent.llm.providers.http_providers import AnthropicProvider, GeminiProvider, OpenAIProvider
from agent.llm.providers.mock import MockProvider, TemplateProvider
from agent.llm.replay import ReplayProvider, prompt_hash
from agent.llm.schemas import NarrativeOut


def mk(tmp_path, provider, **over):
    cfg = load_llm_config()
    cfg.update(over)
    return LLMClient(cfg, provider=provider, logger=LLMCallLogger(tmp_path / "llm", "2026-10-02"))


PAYLOAD = {"facts": {"sox_ret_pct": {"label": "SOX", "value": -1.8, "text": "-1.80%"}}, "regime": "neutral",
           "regime_rationale": "x", "net_exposure_intent": "hold", "estimated_cash_ratio_text": "5.00%",
           "net_flow_text": "+0 元"}


def test_prompt_versioning():
    sysm, user, ver = load_prompt("event_extractor_v1")
    assert "untrusted" in sysm and "{INPUT_JSON}" in user and ver.startswith("event_extractor_v1@")


def test_make_provider_variants():
    assert make_provider({"provider": "mock"}).name == "mock"
    assert make_provider({"provider": "template"}).name == "template"
    assert isinstance(make_provider({"provider": "replay", "replay_roots": []}), ReplayProvider)
    with pytest.raises(ValueError):
        make_provider({"provider": "openai", "model": None})


def test_real_providers_request_shapes():
    req = LLMRequest("market_narrator", "SYS", "USER", "v1", json_mode=True, temperature=0, seed=7, max_tokens=99)
    g = GeminiProvider("gemini-x").build(req)
    assert g["generationConfig"]["responseMimeType"] == "application/json" and g["generationConfig"]["seed"] == 7
    assert GeminiProvider.parse({"candidates": [{"content": {"parts": [{"text": "{}"}]}}],
                                 "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1}})[:3] == ("{}", 3, 1)
    o = OpenAIProvider("gpt-x").build(req)
    assert o["response_format"] == {"type": "json_object"} and o["messages"][0]["role"] == "system"
    assert OpenAIProvider.parse({"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 2,
                                 "completion_tokens": 1}})[:3] == ("{}", 2, 1)
    a = AnthropicProvider("claude-x").build(req)
    assert a["system"] == "SYS" and a["max_tokens"] == 99
    assert AnthropicProvider.parse({"content": [{"type": "text", "text": "{}"}],
                                    "usage": {"input_tokens": 5, "output_tokens": 2}})[:3] == ("{}", 5, 2)


def test_real_provider_without_key_falls_back(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import agent.llm.env as E
    monkeypatch.setattr(E, "_LOADED", True)
    c = mk(tmp_path, OpenAIProvider("gpt-x"))
    assert not c.enabled
    assert c.generate_structured(c.request("market_narrator", "market_narrator_v1", PAYLOAD), NarrativeOut) is None


def test_template_provider_disabled(tmp_path):
    c = mk(tmp_path, TemplateProvider())
    assert not c.enabled
    assert c.generate_text(c.request("market_narrator", "market_narrator_v1", PAYLOAD)) is None


def test_mock_structured_ok_and_logged(tmp_path):
    c = mk(tmp_path, MockProvider())
    out = c.generate_structured(c.request("market_narrator", "market_narrator_v1", PAYLOAD), NarrativeOut)
    assert isinstance(out, NarrativeOut)
    rec = [json.loads(x) for x in (tmp_path / "llm" / "20261002" / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    r = rec[-1]
    for k in ("timestamp", "provider", "model", "prompt_version", "prompt_hash", "temperature", "seed",
              "input_fact_ids", "response", "parsed_output", "latency_sec", "token_usage", "retry_count", "status"):
        assert k in r, k
    assert r["status"] == "ok"


@pytest.mark.parametrize("mode,status", [("rate_limit", "LLMRateLimited"), ("server_error", "LLMServerError"),
                                         ("timeout", "LLMTimeout"), ("bad_json", "format_error")])
def test_retries_then_drop(tmp_path, mode, status):
    p = MockProvider(mode=mode)
    c = mk(tmp_path, p, retries=2)
    assert c.generate_structured(c.request("market_narrator", "market_narrator_v1", PAYLOAD), NarrativeOut) is None
    assert p.calls == 3                                  # 1 + 2 retries
    st = [r["status"] for r in c.logger.records]
    assert st.count(status) == 3 and st[-1] == "dropped"


def test_call_budget(tmp_path):
    c = mk(tmp_path, MockProvider(), max_calls_per_day=1)
    r = c.request("market_narrator", "market_narrator_v1", PAYLOAD)
    assert c.generate_structured(r, NarrativeOut) is not None
    assert c.generate_structured(r, NarrativeOut) is None
    assert c.logger.records[-1]["status"] == "skipped_budget"


def test_time_budget(tmp_path):
    c = mk(tmp_path, MockProvider(), total_budget_sec=0)
    assert c.generate_structured(c.request("market_narrator", "market_narrator_v1", PAYLOAD), NarrativeOut) is None


def test_key_never_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-SECRET-123")
    lg = LLMCallLogger(tmp_path, "2026-10-02")
    lg.log({"status": "ok", "response": "echo sk-test-SECRET-123"})
    txt = (tmp_path / "20261002" / "calls.jsonl").read_text(encoding="utf-8")
    assert "SECRET" not in txt and "REDACTED" in txt
    assert redact("a sk-test-SECRET-123 b") == "a ***REDACTED*** b"


def test_dotenv_does_not_override(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("GEMINI_API_KEY=from_file\nOPENAI_API_KEY=from_file\n# comment\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "from_env")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    load_dotenv(f)
    assert os.environ["GEMINI_API_KEY"] == "from_file" and os.environ["OPENAI_API_KEY"] == "from_env"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_env_files_ignored_by_git():
    from pathlib import Path
    gi = (Path(__file__).resolve().parents[2] / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gi.split()
    ex = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=\n" in ex and "sk-" not in ex


def test_replay_returns_recorded_response(tmp_path):
    c = mk(tmp_path, MockProvider())
    req = c.request("market_narrator", "market_narrator_v1", PAYLOAD)
    a = c.generate_structured(req, NarrativeOut)
    rp = ReplayProvider([tmp_path / "llm"])
    c2 = mk(tmp_path / "r", rp)
    for _ in range(100):
        b = c2.generate_structured(req, NarrativeOut)
        assert b == a
    assert prompt_hash(req.task, req.system, req.prompt) in rp.store
    miss = c2.request("market_narrator", "market_narrator_v1", dict(PAYLOAD, regime="risk_on"))
    assert c2.generate_structured(miss, NarrativeOut) is None          # replay miss -> fallback, no API call
