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


# Round 07: the narrative must never recommend an action or contradict the quant decision
RECOMMEND = re.compile(r"(建議|宜|應該?|可考慮|不妨)\s*(大幅|適度|小幅|逢低|逢高|積極)?\s*"
                       r"(加碼|減碼|增持|減持|買進|賣出|出清|進場|出場|布局|調高|調降)")
TRADE_UP = re.compile(r"(加碼|增持|買進|調高持股)")
TRADE_DOWN = re.compile(r"(減碼|減持|賣出|出清|調降持股)")


def decision_contradiction(text: str, action: str | None) -> str | None:
    """None when consistent. action: NO_TRADE / BUY / SELL (thesis) or hold / increase / decrease (market posture)."""
    if RECOMMEND.search(text or ""):
        return "recommends an investment action"
    a = (action or "").upper()
    if a in ("NO_TRADE", "HOLD") and (TRADE_UP.search(text or "") or TRADE_DOWN.search(text or "")):
        return f"text describes trading but the decision is {a}"
    if a in ("BUY", "INCREASE") and TRADE_DOWN.search(text or ""):
        return f"text describes selling but the decision is {a}"
    if a in ("SELL", "DECREASE") and TRADE_UP.search(text or ""):
        return f"text describes buying but the decision is {a}"
    return None


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
    action = payload.get("net_exposure_intent") or (payload.get("item") or {}).get("action")
    contra = decision_contradiction((logic or "") + " " + (counter or ""), action)
    if contra:
        issues.append(f"decision contradiction: {contra}")
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
