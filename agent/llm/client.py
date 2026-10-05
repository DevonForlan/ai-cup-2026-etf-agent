"""LLMClient: the only path through which the agent talks to a model.

Responsibilities: provider selection, prompt versioning, timeouts/retries, call + token + cost +
time budgets, JSON parsing, pydantic validation, optional semantic validator (grounding), logging,
replay. On any failure it returns None — callers must fall back to deterministic behaviour.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from agent.config import ROOT
from agent.llm.base import (LLMError, LLMFormatError, LLMProvider, LLMRawResponse, LLMRequest,
                            LLMUnavailable)
from agent.llm.logging import LLMCallLogger
from agent.llm.replay import prompt_hash

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def load_llm_config(path: str | Path = "config/llm.yaml") -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def load_prompt(name: str) -> tuple[str, str, str]:
    """Returns (system, user_template, prompt_version). File format: '### SYSTEM' / '### USER' sections.
    prompt_version = <file stem>@<sha256[:8] of file content> (file is under git)."""
    import hashlib
    p = PROMPT_DIR / f"{name}.txt"
    raw = p.read_text(encoding="utf-8")
    sys_part = raw.split("### SYSTEM", 1)[1].split("### USER", 1)[0].strip()
    user_part = raw.split("### USER", 1)[1].strip()
    return sys_part, user_part, f"{p.stem}@{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8]}"


def make_provider(cfg: dict) -> LLMProvider:
    name = (cfg.get("provider") or "template").lower()
    model = cfg.get("model") or ""
    if name == "mock":
        from agent.llm.providers.mock import MockProvider
        return MockProvider(model or "mock-rules-v1", cfg.get("mock_mode", "normal"), cfg.get("mock_latency", 0.0))
    if name == "replay":
        from agent.llm.replay import ReplayProvider
        return ReplayProvider([Path(x) for x in cfg.get("replay_roots", [])] or None)
    if name == "template" or cfg.get("enabled") is False:     # a disabled provider config means template
        from agent.llm.providers.mock import TemplateProvider
        return TemplateProvider()
    if name in ("claude_agent_sdk", "claude-agent-sdk"):
        from agent.llm.providers.claude_agent_sdk import ClaudeAgentSDKProvider
        return ClaudeAgentSDKProvider(model or None, cfg)
    from agent.llm.providers import http_providers as H
    cls = {"google": H.GeminiProvider, "gemini": H.GeminiProvider, "openai": H.OpenAIProvider,
           "anthropic": H.AnthropicProvider}[name]
    if not model:
        raise ValueError(f"config/llm.yaml: model must be set for provider {name}")
    return cls(model, cfg.get("endpoint"))


def _extract_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(json)?", "", t).rstrip("`").strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            raise LLMFormatError("no JSON object in response")
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise LLMFormatError(f"invalid JSON: {e}") from e


@dataclass
class Budget:
    max_calls: int
    max_tokens: int
    max_cost: float
    total_sec: float
    calls: int = 0
    tokens: int = 0
    cost: float = 0.0
    started: float = field(default_factory=time.perf_counter)

    def exhausted(self) -> str | None:
        if self.calls >= self.max_calls:
            return "max_calls_per_day"
        if self.tokens >= self.max_tokens:
            return "max_tokens_per_day"
        if self.cost >= self.max_cost:
            return "max_cost_per_day"
        if time.perf_counter() - self.started >= self.total_sec:
            return "total_budget_sec"
        return None


class LLMClient:
    def __init__(self, cfg: dict | None = None, provider: LLMProvider | None = None,
                 logger: LLMCallLogger | None = None, run_date: str | None = None):
        self.cfg = cfg or load_llm_config()
        self.provider = provider or make_provider(self.cfg)
        self.logger = logger or LLMCallLogger(run_date=run_date, enabled=bool(self.cfg.get("log_calls", True)))
        self.budget = Budget(int(self.cfg.get("max_calls_per_day", 60)), int(self.cfg.get("max_tokens_per_day", 2e5)),
                             float(self.cfg.get("max_cost_per_day_usd", 2.0)), float(self.cfg.get("total_budget_sec", 120)))
        price = self.cfg.get("price_usd_per_1m_tokens") or {}
        self.price_in, self.price_out = price.get("input"), price.get("output")

    # ------------------------------------------------------------------ properties
    @property
    def provider_name(self) -> str:
        return self.provider.name

    @property
    def model_version(self) -> str:
        return getattr(self.provider, "model", "") or ""

    @property
    def enabled(self) -> bool:
        return self.provider.name != "template" and self.provider.available()

    def request(self, task: str, prompt_name: str, payload: dict, input_fact_ids: list[str] | None = None) -> LLMRequest:
        system, user_t, version = load_prompt(prompt_name)
        body = user_t.replace("{INPUT_JSON}", "<INPUT_JSON>\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True)
                              + "\n</INPUT_JSON>")
        return LLMRequest(task=task, system=system, prompt=body, prompt_version=version,
                          temperature=float(self.cfg.get("temperature", 0.0)), seed=self.cfg.get("seed"),
                          max_tokens=int(self.cfg.get("max_tokens", 1200)), timeout=float(self.cfg.get("timeout_sec", 30)),
                          input_fact_ids=list(input_fact_ids or []))

    def _cost(self, it: int | None, ot: int | None) -> float | None:
        if self.price_in is None or self.price_out is None:
            return None
        return ((it or 0) * self.price_in + (ot or 0) * self.price_out) / 1e6

    # ------------------------------------------------------------------ calls
    def generate_text(self, req: LLMRequest) -> str | None:
        r = self._call(req, None, None, json_mode=False)
        return r if isinstance(r, str) else None

    def generate_structured(self, req: LLMRequest, model: type[BaseModel], validator=None) -> BaseModel | None:
        """Parse + pydantic-validate + optional semantic validator(obj) -> list[str] problems.
        Format/validation problems are retried; persistent failure -> None (caller falls back)."""
        return self._call(req, model, validator, json_mode=True)

    def _call(self, req: LLMRequest, model, validator, json_mode: bool):
        h = prompt_hash(req.task, req.system, req.prompt)
        base = {"task": req.task, "provider": self.provider.name, "model": self.model_version,
                "prompt_version": req.prompt_version, "prompt_hash": h, "temperature": req.temperature,
                "seed": req.seed, "input_fact_ids": req.input_fact_ids}
        if not self.enabled:
            self.logger.log({**base, "status": "disabled"})
            return None
        why = self.budget.exhausted() if self.provider.name != "replay" else None   # replay costs nothing
        if why:
            self.logger.log({**base, "status": "skipped_budget", "reason": why})
            return None
        retries = int(self.cfg.get("retries", 2))
        last_err, raw = None, None
        for attempt in range(retries + 1):
            t0 = time.perf_counter()
            try:
                self.budget.calls += 1
                raw = self.provider.complete(req)
                it = raw.input_tokens or 0
                ot = raw.output_tokens or 0
                self.budget.tokens += it + ot
                cost = self._cost(it, ot)
                self.budget.cost += cost or 0.0
                if not json_mode:
                    self._log_ok(base, raw, raw.text, None, attempt, cost, t0)
                    return raw.text
                data = _extract_json(raw.text)
                obj = model.model_validate(data)
                problems = validator(obj) if validator else []
                if problems:
                    raise LLMFormatError("semantic: " + "; ".join(problems[:5]))
                self._log_ok(base, raw, raw.text, obj.model_dump(), attempt, cost, t0)
                return obj
            except (LLMFormatError, ValidationError) as e:
                last_err = e
                self.logger.log({**base, "status": "format_error", "error": str(e)[:500], "retry_count": attempt,
                                 "response": None if raw is None else raw.text[:4000],
                                 "latency_sec": time.perf_counter() - t0})
            except LLMUnavailable as e:
                self.logger.log({**base, "status": "unavailable", "error": str(e)[:300], "retry_count": attempt})
                return None
            except LLMError as e:
                last_err = e
                self.logger.log({**base, "status": type(e).__name__, "error": str(e)[:300], "retry_count": attempt,
                                 "latency_sec": time.perf_counter() - t0})
                if not e.retryable:
                    return None
            if self.provider.name != "replay" and self.budget.exhausted():
                break
        self.logger.log({**base, "status": "dropped", "error": str(last_err)[:300], "retry_count": retries})
        return None

    def _log_ok(self, base, raw: LLMRawResponse, text, parsed, attempt, cost, t0):
        self.logger.log({**base, "status": "replay" if self.provider.name == "replay" else "ok",
                         "model_version": raw.model_version, "response": text, "parsed_output": parsed,
                         "latency_sec": round(raw.latency_sec or (time.perf_counter() - t0), 4),
                         "input_tokens": raw.input_tokens, "output_tokens": raw.output_tokens,
                         "token_usage": (raw.input_tokens or 0) + (raw.output_tokens or 0),
                         "cost_usd": cost, "retry_count": attempt, "provider_meta": raw.provider_meta})
