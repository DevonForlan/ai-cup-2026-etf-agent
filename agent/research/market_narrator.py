"""Phase 5A Market Narrator: LLM rewrites market_view.logic / counter_evidence from facts that code
already computed. regime / posture / cash range are NOT model outputs. Any failure -> template text."""
from __future__ import annotations

from agent.llm.client import LLMClient
from agent.llm.interfaces import TemplateMarketNarrator
from agent.llm.schemas import NarrativeOut
from agent.research.reviewer import review_text

LABELS = {"breadth_above_ma20_pct": ("150 檔站上 20 日均線比例", "%"), "advancers_1d": ("前日上漲家數", ""),
          "decliners_1d": ("前日下跌家數", ""), "median_ret_1d_pct": ("1 日報酬中位數", "%"),
          "median_ret_5d_pct": ("5 日報酬中位數", "%"), "median_ret_20d_pct": ("20 日報酬中位數", "%"),
          "sp500_ret_pct": ("S&P500 隔夜", "%"), "nasdaq100_ret_pct": ("Nasdaq100 隔夜", "%"),
          "sox_ret_pct": ("費城半導體 SOX 隔夜", "%"), "tsm_adr_ret_pct": ("TSM ADR 隔夜", "%"),
          "txf_night_ret_pct": ("台指期夜盤相對前日結算", "%"), "usdtwd_ret_pct": ("USD/TWD", "%")}


def _fmt(k: str, v) -> str:
    unit = LABELS.get(k, (k, ""))[1]
    if unit == "%":
        return f"{v:+.2f}%" if "ret" in k else f"{v:.1f}%"
    return f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)


class LLMMarketNarrator(TemplateMarketNarrator):
    def __init__(self, client: LLMClient):
        self.client = client
        self.used_llm = False
        self.review: str | None = None

    def market_logic(self, v: dict, regime: str, why: str, cash_range, posture) -> str:
        tmpl = super().market_logic(v, regime, why, cash_range, posture)
        if not self.client.enabled:
            return tmpl
        facts = {k: {"label": LABELS.get(k, (k,))[0], "value": x, "text": _fmt(k, x)} for k, x in v.items()
                 if isinstance(x, (int, float))}
        payload = {"facts": facts, "regime": regime, "regime_rationale": why,
                   "net_exposure_intent": posture.net_exposure_intent,
                   "estimated_cash_ratio_text": f"{float(posture.cash_ratio_no_fee):.2%}",
                   "net_flow_text": f"{float(posture.net_flow):+,.0f} 元"}
        req = self.client.request("market_narrator", "market_narrator_v1", payload, list(facts))
        out = self.client.generate_structured(req, NarrativeOut)
        if out is None:
            return tmpl
        rv = review_text(out.logic, out.counter_evidence, out.fact_refs, payload, set(facts))
        self.review = rv.verdict
        if rv.verdict != "PASS":
            return tmpl
        self.used_llm = True
        self._counter = out.counter_evidence
        # the evidence placeholder is appended by code so the reference is guaranteed
        return out.logic.rstrip("。") + "（{{fact:market}}{{fact:overnight}}）。"

    def market_counter(self, v: dict, regime: str) -> str | None:
        if self.used_llm:
            return getattr(self, "_counter", None)
        return super().market_counter(v, regime)
