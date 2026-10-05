"""ReplayProvider: answers from previously logged responses (logs/llm/**/calls.jsonl), keyed by the
prompt hash. snapshot + git sha + replay log => identical narrative / events without calling any API."""
from __future__ import annotations

import json
from pathlib import Path

from agent.config import ROOT
from agent.llm.base import LLMProvider, LLMRawResponse, LLMRequest, LLMUnavailable


def prompt_hash(task: str, system: str, prompt: str) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(f"{task}\x00{system}\x00{prompt}".encode("utf-8")).hexdigest()


class ReplayProvider(LLMProvider):
    name = "replay"

    def __init__(self, roots: list[Path] | None = None):
        self.model = "replay"
        self.store: dict[str, dict] = {}
        for root in roots or [ROOT / "logs" / "llm"]:
            for p in sorted(Path(root).rglob("calls.jsonl")):
                for line in p.read_text(encoding="utf-8").splitlines():
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("status") == "ok" and r.get("response") is not None:
                        self.store[r["prompt_hash"]] = r

    def complete(self, req: LLMRequest) -> LLMRawResponse:
        h = prompt_hash(req.task, req.system, req.prompt)
        r = self.store.get(h)
        if r is None:
            raise LLMUnavailable(f"replay miss {h[:19]}")
        return LLMRawResponse(r["response"], r.get("model_version", "replay"), r.get("input_tokens"),
                              r.get("output_tokens"), 0.0, {"replayed_from": r.get("timestamp"),
                                                            "original_provider": r.get("provider")})
