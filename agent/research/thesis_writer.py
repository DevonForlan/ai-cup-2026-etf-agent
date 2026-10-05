"""Phase 5A Thesis Writer: one batched LLM call per day writes logic / counter_evidence for decided
items (decisions + grouped holds). It cannot change ticker, action, weight, rank or orders: the
builder calls `prepare()` AFTER the portfolio is final and only text fields are taken from here.
Items failing the grounding review fall back to the deterministic template individually."""
from __future__ import annotations

from agent.llm.client import LLMClient
from agent.llm.interfaces import TemplateThesisWriter
from agent.llm.schemas import ThesisOut
from agent.research.reviewer import review_text

FACT_LABELS = {"close_prev": "前日收盤", "ret_20d_pct": "20 日報酬", "ret_60d_pct": "60 日報酬",
               "rs_20d_vs_median_pct": "20 日相對強弱", "dist_52w_high_pct": "距 52 週高點",
               "volatility_20d_ann_pct": "20 日年化波動", "inst_net_5d_lots": "近 5 日法人淨買賣(張)",
               "inst_net_20d_lots": "近 20 日法人淨買賣(張)", "revenue_yoy_pct": "月營收年增",
               "revenue_mom_pct": "月營收月增"}


def _facts(ticker: str, values: dict, limit: int = 6) -> dict:
    out = {}
    for k, v in values.items():
        if k not in FACT_LABELS or not isinstance(v, (int, float)):
            continue
        txt = f"{v:,.0f}" if k.endswith("_lots") else (f"{v:,.2f}" if k == "close_prev" else f"{v:+.1f}%")
        out[f"{ticker}:{k}"] = {"label": FACT_LABELS[k], "value": v, "text": txt}
        if len(out) >= limit:
            break
    return out


class LLMThesisWriter(TemplateThesisWriter):
    def __init__(self, client: LLMClient, max_items: int = 35):
        self.client = client
        self.max_items = max_items
        self.texts: dict[str, tuple[str, str | None]] = {}
        self.stats = {"items": 0, "llm_used": 0, "fallback": 0, "review_fail": 0}

    def prepare(self, items: list[dict]) -> None:
        """items: {key, ticker_label, action, rank_text, values(dict) or group_values(list)}"""
        if not self.client.enabled or not items:
            return
        items = items[: self.max_items]
        payload_items, allowed = [], {}
        for it in items:
            facts = {}
            for t, vals in it["fact_sets"]:
                facts.update(_facts(t, vals, 6 if len(it["fact_sets"]) == 1 else 2))
            allowed[it["key"]] = facts
            payload_items.append({"key": it["key"], "ticker_label": it["ticker_label"], "action": it["action"],
                                  "rank_text": it.get("rank_text", "-"), "facts": facts})
        payload = {"items": payload_items}
        req = self.client.request("thesis_writer", "thesis_writer_v1", payload,
                                  [f for v in allowed.values() for f in v])
        out = self.client.generate_structured(req, ThesisOut)
        self.stats["items"] += len(items)
        if out is None:
            self.stats["fallback"] += len(items)
            return
        got = {x.key: x for x in out.items}
        for it, pi in zip(items, payload_items):
            x = got.get(it["key"])
            if x is None:
                self.stats["fallback"] += 1
                continue
            rv = review_text(x.logic, x.counter_evidence, x.fact_refs, {"item": pi}, set(allowed[it["key"]]))
            if rv.verdict != "PASS":
                self.stats["review_fail"] += 1
                self.stats["fallback"] += 1
                continue
            self.texts[it["key"]] = (x.logic, x.counter_evidence)
            self.stats["llm_used"] += 1

    def _llm(self, key: str, placeholder: str):
        if key in self.texts:
            logic, counter = self.texts[key]
            return logic.rstrip("。") + f"（{placeholder}）。", counter
        return None

    def decision_logic(self, c: dict) -> str:
        r = self._llm(f"dec:{c['ticker']}", "{{fact:" + c["ticker"] + "}}")
        return r[0] if r else super().decision_logic(c)

    def counter_evidence(self, c: dict) -> str | None:
        r = self._llm(f"dec:{c['ticker']}", "")
        return r[1] if r else super().counter_evidence(c)

    def hold_logic_keyed(self, key: str, items: list, band: float, placeholders: str) -> str:
        r = self._llm(key, placeholders)
        return r[0] if r else super().hold_logic(items, band)
