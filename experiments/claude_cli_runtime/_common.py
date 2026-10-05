"""Shared helpers for the Claude Code CLI runtime experiments (Round 06B). Calls run SEQUENTIALLY through the
user's own logged-in, unmodified claude CLI (`claude -p`), NARRATIVE_LOCKED profile unless stated otherwise."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "results"

from agent.llm.base import LLMError, LLMRequest  # noqa: E402,F401
from agent.llm.grounding import allowed_numbers, bad_refs, ungrounded_numbers  # noqa: E402,F401
from agent.llm.providers.claude_cli import ClaudeCodeCLIProvider  # noqa: E402
from agent.research.reviewer import FORBIDDEN  # noqa: E402,F401

CFG = {"provider": "claude_cli", "max_turns": 3, "prompt_guard": "claude_cli_narrative_v1",
       "claude_cli": {"profile": "NARRATIVE_LOCKED", "working_dir": "runtime/claude_cli"}}

SMOKE_SCHEMA = {"type": "object", "additionalProperties": False,
                "properties": {"market_view": {"type": "string"}, "counter_evidence": {"type": "string"},
                               "fact_refs": {"type": "array", "items": {"type": "string"}}},
                "required": ["market_view", "counter_evidence", "fact_refs"]}

SMOKE_FACTS = {"facts": {"F1": {"statement": "TAIEX 20-day trend positive"},
                         "F2": {"statement": "SOX overnight -0.4%", "values": {"sox_overnight_pct": -0.4}}},
               "quant_decision": {"regime": "neutral", "posture": "hold", "orders": []}}

TICKER_RE = re.compile(r"(?<![\d.])\d{4}(?![\d.%])")


def provider(profile: str = "NARRATIVE_LOCKED") -> ClaudeCodeCLIProvider:
    p = ClaudeCodeCLIProvider(None, dict(CFG, claude_cli=dict(CFG["claude_cli"], profile=profile)))
    p.schema_overrides["smoke"] = SMOKE_SCHEMA
    return p


def call(p, payload: dict, task: str = "smoke", system: str = "Explain the facts.", timeout: float = 120.0):
    prompt = "<INPUT_JSON>\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n</INPUT_JSON>"
    t0 = time.perf_counter()
    try:
        r = p.complete(LLMRequest(task=task, system=system, prompt=prompt, prompt_version="06b", timeout=timeout))
        return {"ok": True, "text": r.text, "model": r.model_version, "latency": time.perf_counter() - t0,
                "meta": r.provider_meta, "in_tok": r.input_tokens, "out_tok": r.output_tokens}
    except LLMError as e:
        return {"ok": False, "error": type(e).__name__, "category": getattr(e, "category", None), "detail": str(e)[:300],
                "latency": time.perf_counter() - t0, "meta": p.last_meta}


def grounding(payload: dict, obj: dict, known_tickers: set[str] = frozenset()) -> dict:
    texts = " ".join(str(v) for k, v in obj.items() if k != "fact_refs")
    ids = set(payload.get("facts", {}))
    return {"unknown_fact_ids": bad_refs(obj.get("fact_refs") or [], ids),
            "ungrounded_numbers": ungrounded_numbers(texts, allowed_numbers(payload)),
            "new_tickers": sorted(set(TICKER_RE.findall(texts)) - set(known_tickers)
                                  - set(TICKER_RE.findall(json.dumps(payload, ensure_ascii=False)))),
            "forbidden_instruction": bool(FORBIDDEN.search(texts))}


def grounded(g: dict) -> bool:
    return not (g["unknown_fact_ids"] or g["ungrounded_numbers"] or g["new_tickers"] or g["forbidden_instruction"])


def count_procs(image: str) -> int:
    try:
        r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"], capture_output=True,
                           text=True, timeout=30)
        return sum(1 for line in r.stdout.splitlines() if line.lower().startswith(f'"{image.lower()}"'))
    except Exception:  # noqa: BLE001
        return -1


def repo_state() -> dict:
    st = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    from agent.ops.common import sha256_file
    return {"porcelain": st, "strategy_sha": sha256_file(ROOT / "config" / "strategy_quant_v1.yaml")}


def write(name: str, obj) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{name}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return p
