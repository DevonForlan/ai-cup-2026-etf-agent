"""Phase 5A Reviewer — checks generated text, never edits portfolios/orders/weights.

Deterministic checks (always): cited ids exist, every number grounded in the given facts, text not
empty, no forbidden trading instructions. Optional LLM reviewer can only downgrade (PASS->REWRITE/FAIL).
Verdict: PASS | REWRITE | FAIL."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent.llm.grounding import allowed_numbers, bad_refs, ungrounded_numbers

FORBIDDEN = re.compile(r"(target_weight|下單|買進\s*\d|賣出\s*\d|權重設為|set\s+(the\s+)?weight|buy\s+ticker|"
                       r"sell\s+ticker|ignore\s+(all\s+)?previous|system\s+prompt|忽略(先前|以上|之前)的?指令)", re.I)


@dataclass
class Review:
    verdict: str
    issues: list[str] = field(default_factory=list)


def review_text(logic: str, counter: str | None, refs: list[str], payload: dict, allowed_ids: set[str],
                llm_client=None) -> Review:
    issues = []
    if not logic or len(logic.strip()) < 20:
        issues.append("logic too short")
    br = bad_refs(refs, allowed_ids)
    if br:
        issues.append(f"unknown refs {br}")
    allowed = allowed_numbers(payload)
    un = ungrounded_numbers((logic or "") + " " + (counter or ""), allowed)
    if un:
        issues.append(f"ungrounded numbers {un}")
    if FORBIDDEN.search((logic or "") + (counter or "")):
        issues.append("contains trading instruction")
    if issues:
        return Review("FAIL", issues)
    if not refs:
        return Review("REWRITE", ["no fact_refs cited"])
    if llm_client is not None and llm_client.enabled:
        from agent.llm.schemas import ReviewOut
        req = llm_client.request("reviewer", "reviewer_v1", {"logic": logic, "counter_evidence": counter,
                                                              "facts": payload})
        r = llm_client.generate_structured(req, ReviewOut)
        if r is not None and r.verdict != "PASS":
            return Review(r.verdict, list(r.issues))
    return Review("PASS", [])
