"""Real-provider adapters over plain HTTPS (no SDK dependency).

NOT EXERCISED in Round 04: no API key was available in the environment, so these adapters are
only covered by request-construction / response-parsing unit tests with recorded-shape fixtures.
Model names and endpoints are configuration (config/llm.yaml); verify them before enabling."""
from __future__ import annotations

import time

import httpx

from agent.llm.base import (LLMProvider, LLMRateLimited, LLMRawResponse, LLMRequest, LLMServerError,
                            LLMTimeout, LLMUnavailable)
from agent.llm.env import get_key


def _raise_for(r: httpx.Response) -> None:
    if r.status_code == 429:
        raise LLMRateLimited(f"429 from provider")
    if r.status_code >= 500:
        raise LLMServerError(f"{r.status_code} from provider")
    if r.status_code >= 400:
        raise LLMUnavailable(f"{r.status_code} from provider: {r.text[:200]}")


class _HTTPProvider(LLMProvider):
    key_env = ""
    endpoint = ""

    def __init__(self, model: str, endpoint: str | None = None):
        self.model = model
        if endpoint:
            self.endpoint = endpoint

    def available(self) -> bool:
        return bool(get_key(self.key_env))

    def _post(self, url: str, headers: dict, body: dict, timeout: float) -> tuple[dict, float]:
        t0 = time.perf_counter()
        try:
            r = httpx.post(url, headers=headers, json=body, timeout=timeout)
        except httpx.TimeoutException as e:
            raise LLMTimeout(str(e)) from e
        except httpx.HTTPError as e:
            raise LLMServerError(str(e)) from e
        _raise_for(r)
        return r.json(), time.perf_counter() - t0


class GeminiProvider(_HTTPProvider):
    name = "google"
    key_env = "GEMINI_API_KEY"
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def build(self, req: LLMRequest) -> dict:
        cfg = {"temperature": req.temperature, "maxOutputTokens": req.max_tokens}
        if req.seed is not None:
            cfg["seed"] = req.seed
        if req.json_mode:
            cfg["responseMimeType"] = "application/json"
        return {"systemInstruction": {"parts": [{"text": req.system}]},
                "contents": [{"role": "user", "parts": [{"text": req.prompt}]}], "generationConfig": cfg}

    @staticmethod
    def parse(j: dict) -> tuple[str, int | None, int | None, str]:
        text = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        u = j.get("usageMetadata", {})
        return text, u.get("promptTokenCount"), u.get("candidatesTokenCount"), j.get("modelVersion", "")

    def complete(self, req: LLMRequest) -> LLMRawResponse:
        key = get_key(self.key_env)
        if not key:
            raise LLMUnavailable("GEMINI_API_KEY not set")
        j, lat = self._post(self.endpoint.format(model=self.model), {"x-goog-api-key": key}, self.build(req), req.timeout)
        text, it, ot, mv = self.parse(j)
        return LLMRawResponse(text, mv or self.model, it, ot, lat)


class OpenAIProvider(_HTTPProvider):
    name = "openai"
    key_env = "OPENAI_API_KEY"
    endpoint = "https://api.openai.com/v1/chat/completions"

    def build(self, req: LLMRequest) -> dict:
        b = {"model": self.model, "temperature": req.temperature, "max_tokens": req.max_tokens,
             "messages": [{"role": "system", "content": req.system}, {"role": "user", "content": req.prompt}]}
        if req.seed is not None:
            b["seed"] = req.seed
        if req.json_mode:
            b["response_format"] = {"type": "json_object"}
        return b

    @staticmethod
    def parse(j: dict) -> tuple[str, int | None, int | None, str]:
        u = j.get("usage", {})
        return (j["choices"][0]["message"]["content"], u.get("prompt_tokens"), u.get("completion_tokens"),
                j.get("model", ""))

    def complete(self, req: LLMRequest) -> LLMRawResponse:
        key = get_key(self.key_env)
        if not key:
            raise LLMUnavailable("OPENAI_API_KEY not set")
        j, lat = self._post(self.endpoint, {"Authorization": f"Bearer {key}"}, self.build(req), req.timeout)
        text, it, ot, mv = self.parse(j)
        return LLMRawResponse(text, mv or self.model, it, ot, lat)


class AnthropicProvider(_HTTPProvider):
    name = "anthropic"
    key_env = "ANTHROPIC_API_KEY"
    endpoint = "https://api.anthropic.com/v1/messages"

    def build(self, req: LLMRequest) -> dict:
        # JSON mode is enforced by the prompt + client-side schema validation.
        return {"model": self.model, "max_tokens": req.max_tokens, "temperature": req.temperature,
                "system": req.system, "messages": [{"role": "user", "content": req.prompt}]}

    @staticmethod
    def parse(j: dict) -> tuple[str, int | None, int | None, str]:
        text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        u = j.get("usage", {})
        return text, u.get("input_tokens"), u.get("output_tokens"), j.get("model", "")

    def complete(self, req: LLMRequest) -> LLMRawResponse:
        key = get_key(self.key_env)
        if not key:
            raise LLMUnavailable("ANTHROPIC_API_KEY not set")
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        j, lat = self._post(self.endpoint, headers, self.build(req), req.timeout)
        text, it, ot, mv = self.parse(j)
        return LLMRawResponse(text, mv or self.model, it, ot, lat)
