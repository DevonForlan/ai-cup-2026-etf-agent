"""Numeric / reference grounding checks applied to every piece of LLM output.

Rule: every number that appears in generated text must appear in the INPUT the model was given
(fact texts, fact values, labels, document text). Every cited id must be one of the ids provided.
"""
from __future__ import annotations

import json
import re

NUM_RE = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?")


def _norm(tok: str) -> str | None:
    t = tok.replace(",", "").lstrip("+")
    try:
        x = float(t)
    except ValueError:
        return None
    return f"{abs(x):.4f}".rstrip("0").rstrip(".")


def numbers_in(text: str) -> set[str]:
    out = set()
    for m in NUM_RE.finditer(text or ""):
        n = _norm(m.group(0))
        if n is not None:
            out.add(n)
    return out


def allowed_numbers(payload) -> set[str]:
    """All numbers present anywhere in the input payload (strings and numeric values, incl. keys)."""
    s = json.dumps(payload, ensure_ascii=False)
    nums = numbers_in(s)
    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            for nd in (0, 1, 2, 3, 4):
                nums.add(_norm(f"{round(float(x), nd)}") or "")
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(payload)
    return nums


def ungrounded_numbers(text: str, allowed: set[str]) -> list[str]:
    return sorted(n for n in numbers_in(text) if n not in allowed)


def bad_refs(refs: list[str], allowed_ids: set[str]) -> list[str]:
    return [r for r in refs if r not in allowed_ids]
