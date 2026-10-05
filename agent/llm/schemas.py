"""Structured outputs expected from LLM roles (validated with pydantic before use)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EVENT_TYPES = ("revenue", "earnings", "guidance", "capex", "order", "product", "regulatory", "management",
               "litigation", "merger", "dividend", "supply_chain", "industry", "macro", "other")
EventType = Literal["revenue", "earnings", "guidance", "capex", "order", "product", "regulatory", "management",
                    "litigation", "merger", "dividend", "supply_chain", "industry", "macro", "other"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventItem(_Strict):
    ticker: str = Field(min_length=1, max_length=12)
    source_ids: list[str] = Field(min_length=1, max_length=5)
    event_type: EventType
    direction: Literal["positive", "neutral", "negative"]
    confidence: float = Field(ge=0, le=1)
    horizon_days: int = Field(ge=1, le=20)
    summary: str = Field(max_length=200)
    reason: str = Field(default="", max_length=300)
    risk: str = Field(default="", max_length=200)
    fact_refs: list[str] = Field(default_factory=list, max_length=10)


class EventsOut(_Strict):
    events: list[EventItem] = Field(default_factory=list, max_length=60)


class NarrativeOut(_Strict):
    logic: str = Field(min_length=20, max_length=1000)
    counter_evidence: str | None = Field(default=None, max_length=500)
    fact_refs: list[str] = Field(default_factory=list, max_length=12)


class ThesisItem(_Strict):
    key: str
    logic: str = Field(min_length=20, max_length=1000)
    counter_evidence: str | None = Field(default=None, max_length=500)
    fact_refs: list[str] = Field(default_factory=list, max_length=10)


class ThesisOut(_Strict):
    items: list[ThesisItem] = Field(default_factory=list, max_length=60)


class ReviewOut(_Strict):
    verdict: Literal["PASS", "REWRITE", "FAIL"]
    issues: list[str] = Field(default_factory=list)


# --- kept for backward compatibility with Round 02/03 interfaces
class ExtractedEvent(BaseModel):
    ticker: str = Field(pattern=r"^[0-9]{4}$")
    event_type: Literal["revenue", "earnings", "guidance", "order_contract", "capacity", "m_and_a",
                        "regulatory", "dividend", "management", "macro", "other"]
    direction: Literal["positive", "negative", "neutral"]
    horizon_days: int = Field(ge=1, le=60)
    confidence: float = Field(ge=0, le=1)
    published_at: str = Field(pattern=r"\+08:00$")
    summary: str = Field(max_length=300)


class ThesisText(BaseModel):
    logic: str = Field(min_length=20, max_length=1000)
    counter_evidence: str | None = Field(default=None, max_length=500)
    allowed_refs: list[str]


class ReviewResult(BaseModel):
    ok: bool
    issues: list[str]
    reviewer: str
