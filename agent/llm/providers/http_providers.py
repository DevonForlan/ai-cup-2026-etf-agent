"""Real-provider adapters over plain HTTPS (no SDK dependency).

NOT EXERCISED in Round 04: no API key was available in the environment, so these adapters are
only covered by request-construction / response-parsing unit tests with recorded-shape fixtures.
Model names and endpoints are configuration (config/llm.yaml); verify them before enabling."""
from __future__ import annotations

import time

import httpx

from agent.llm.base import (LLMFormatError, LLMProvider, LLMRateLimited, LLMRawResponse, LLMRequest,
                            LLMServerError, LLMTimeout, LLMUnavailable)
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
    key_env_alt: tuple[str, ...] = ()
    endpoint = ""

    def __init__(self, model: str, endpoint: str | None = None):
        self.model = model
        if endpoint:
            self.endpoint = endpoint

    def key(self) -> str | None:
        for n in (self.key_env, *self.key_env_alt):
            v = get_key(n)
            if v:
                return v
        return None

    def available(self) -> bool:
        return bool(self.key())

    def _post(self, url: str, headers: dict, body: dict, timeout: float) -> tuple[dict, float]:
        t0 = time.perf_counter()
        try:
            r = httpx.post(url, headers=headers, json=body, timeout=timeout)
        except httpx.TimeoutException as e:
            raise LLMTimeout(str(e)) from e
        except httpx.HTTPError as e:
            raise LLMServerError(str(e)) from e
        _raise_for(r)
        try:
            return r.json(), time.perf_counter() - t0
        except ValueError as e:
            raise LLMFormatError(f"non-JSON HTTP body: {e}") from e


class GeminiProvider(_HTTPProvider):
    name = "google"
    key_env = "GEMINI_API_KEY"
    key_env_alt = ("GOOGLE_API_KEY",)
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
        cands = j.get("candidates") or []
        parts = ((cands[0].get("content") or {}).get("parts") or []) if cands else []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text:   # blocked prompt / SAFETY / MAX_TOKENS with no text -> format error (client falls back)
            why = (j.get("promptFeedback") or {}).get("blockReason") or (cands[0].get("finishReason") if cands else None)
            raise LLMFormatError(f"gemini: empty response ({why})")
        u = j.get("usageMetadata", {})
        return text, u.get("promptTokenCount"), u.get("candidatesTokenCount"), j.get("modelVersion", "")

    def complete(self, req: LLMRequest) -> LLMRawResponse:
        key = self.key()
        if not key:
            raise LLMUnavailable("GEMINI_API_KEY / GOOGLE_API_KEY not set")
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
        ch = j.get("choices") or []
        text = ((ch[0].get("message") or {}).get("content") or "") if ch else ""
        if not text:
            raise LLMFormatError(f"openai: empty response ({ch[0].get('finish_reason') if ch else 'no choices'})")
        return text, u.get("prompt_tokens"), u.get("completion_tokens"), j.get("model", "")

    def complete(self, req: LLMRequest) -> LLMRawResponse:
        key = self.key()
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
        if not text:
            raise LLMFormatError(f"anthropic: empty response ({j.get('stop_reason')})")
        u = j.get("usage", {})
        return text, u.get("input_tokens"), u.get("output_tokens"), j.get("model", "")

    def complete(self, req: LLMRequest) -> LLMRawResponse:
        key = self.key()
        if not key:
            raise LLMUnavailable("ANTHROPIC_API_KEY not set")
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        j, lat = self._post(self.endpoint, headers, self.build(req), req.timeout)
        text, it, ot, mv = self.parse(j)
        return LLMRawResponse(text, mv or self.model, it, ot, lat)
