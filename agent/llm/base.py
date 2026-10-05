"""Provider-agnostic LLM types.

A provider only turns (system, prompt) into raw text. Everything else — JSON parsing, schema
validation, grounding checks, retries, logging, replay, budgets — lives in agent.llm.client.LLMClient,
so every provider (real or mock) is held to the same rules."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class LLMError(RuntimeError):
    """Base error. `retryable` tells the client whether another attempt may help."""
    retryable = False


class LLMTimeout(LLMError):
    retryable = True


class LLMRateLimited(LLMError):
    retryable = True


class LLMServerError(LLMError):
    retryable = True


class LLMUnavailable(LLMError):
    """No key / provider not configured / budget exhausted. Never retried."""


class LLMFormatError(LLMError):
    """Response could not be parsed or failed schema validation."""
    retryable = True


@dataclass
class LLMRequest:
    task: str                         # event_extractor | market_narrator | thesis_writer | reviewer
    system: str
    prompt: str
    prompt_version: str
    json_mode: bool = True
    temperature: float = 0.0
    seed: int | None = 7
    max_tokens: int = 1024
    timeout: float = 30.0
    input_fact_ids: list[str] = field(default_factory=list)


@dataclass
class LLMRawResponse:
    text: str
    model_version: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_sec: float = 0.0
    provider_meta: dict = field(default_factory=dict)


class LLMProvider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    def complete(self, req: LLMRequest) -> LLMRawResponse: ...

    def available(self) -> bool:
        return True


def estimate_tokens(text: str) -> int:
    """Rough token estimate when a provider does not report usage (CJK ~1 token/char, ASCII ~4 chars/token)."""
    cjk = sum(1 for ch in text if ord(ch) > 0x2E80)
    return cjk + (len(text) - cjk) // 4 + 1
