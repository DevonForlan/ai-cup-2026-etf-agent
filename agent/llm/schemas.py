"""Structured outputs expected from LLM roles (validated with pydantic before use)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExtractedEvent(BaseModel):
    ticker: str = Field(pattern=r"^[0-9]{4}$")
    event_type: Literal["revenue", "earnings", "guidance", "order_contract", "capacity", "m_and_a",
                        "regulatory", "dividend", "management", "macro", "other"]
    direction: Literal["positive", "negative", "neutral"]
    horizon_days: int = Field(ge=1, le=60)
    confidence: float = Field(ge=0, le=1)
    published_at: str = Field(pattern=r"\+08:00$")
    summary: str = Field(max_length=300)          # factual, no numbers that are not in the source text


class ThesisText(BaseModel):
    logic: str = Field(min_length=20, max_length=1000)
    counter_evidence: str | None = Field(default=None, max_length=500)
    allowed_refs: list[str]                       # fact keys given by code; LLM may not add new ones


class ReviewResult(BaseModel):
    ok: bool
    issues: list[str]
    reviewer: str
