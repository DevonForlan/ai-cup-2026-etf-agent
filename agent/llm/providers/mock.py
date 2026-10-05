"""Deterministic offline providers.

MockProvider       rule-based stand-in for a real LLM (keyword event classifier + paraphrasing writer).
                   It reads the INPUT_JSON block that every prompt carries, so it sees exactly what a real
                   model would see. It is NOT an LLM: results obtained with it say nothing about LLM alpha.
TemplateProvider   returns empty output -> callers fall back to the deterministic templates.
Adversarial modes  (for safety tests): obey_injection, hallucinate_number, invent_ticker, bad_json,
                   timeout, rate_limit, server_error, slow.
"""
from __future__ import annotations

import json
import re
import time

from agent.llm.base import (LLMFormatError, LLMProvider, LLMRateLimited, LLMRawResponse, LLMRequest,
                            LLMServerError, LLMTimeout, estimate_tokens)

INPUT_RE = re.compile(r"<INPUT_JSON>\s*(.*?)\s*</INPUT_JSON>", re.S)

# keyword -> (event_type, direction, confidence, horizon_days). First match wins (order matters).
RULES = [
    (r"(營收|營業收入).{0,12}(創新高|成長|增加|年增)", ("revenue", "positive", 0.72, 5)),
    (r"(營收|營業收入).{0,12}(減少|衰退|年減|下滑)", ("revenue", "negative", 0.72, 5)),
    (r"(自結|獲利|每股盈餘|EPS|稅後淨利).{0,12}(成長|增加|創新高|轉盈)", ("earnings", "positive", 0.70, 5)),
    (r"(自結|獲利|每股盈餘|EPS|稅後淨利).{0,12}(衰退|減少|虧損|轉虧)", ("earnings", "negative", 0.70, 5)),
    (r"(上修|調升).{0,6}(財測|展望|目標)", ("guidance", "positive", 0.75, 5)),
    (r"(下修|調降).{0,6}(財測|展望|目標)", ("guidance", "negative", 0.75, 5)),
    (r"(取得|簽訂|接獲).{0,20}(訂單|合約|契約|標案)", ("order", "positive", 0.60, 3)),
    (r"(取得|處分).{0,20}(機器設備|廠房|不動產|使用權資產)", ("capex", "neutral", 0.50, 3)),
    (r"(資本支出|擴廠|新建廠)", ("capex", "positive", 0.55, 5)),
    (r"(訴訟|仲裁|判決|違約|罰鍰|裁罰)", ("litigation", "negative", 0.60, 3)),
    (r"(辭任|解任|異動).{0,10}(董事長|總經理|執行長|財務主管|發言人)|(董事長|總經理|執行長).{0,10}(辭任|異動)",
     ("management", "negative", 0.55, 3)),
    (r"(合併|收購|併購|公開收購)", ("merger", "positive", 0.55, 5)),
    (r"(股利|配息|配股|盈餘分配)", ("dividend", "neutral", 0.50, 3)),
    (r"(法人說明會|法說會)", ("earnings", "neutral", 0.40, 3)),
]


def _input(req: LLMRequest) -> dict:
    m = INPUT_RE.search(req.prompt)
    if not m:
        raise LLMFormatError("mock: no INPUT_JSON block")
    return json.loads(m.group(1))


def classify(text: str):
    for pat, out in RULES:
        if re.search(pat, text):
            return out
    return None


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(self, model: str = "mock-rules-v1", mode: str = "normal", latency: float = 0.0):
        self.model = model
        self.mode = mode
        self.latency = latency
        self.calls = 0

    def complete(self, req: LLMRequest) -> LLMRawResponse:
        self.calls += 1
        t0 = time.perf_counter()
        if self.mode == "timeout":
            raise LLMTimeout("mock timeout")
        if self.mode == "rate_limit":
            raise LLMRateLimited("mock 429")
        if self.mode == "server_error":
            raise LLMServerError("mock 500")
        if self.mode == "slow":
            time.sleep(self.latency or 1.0)
        elif self.latency:
            time.sleep(self.latency)
        if self.mode == "bad_json":
            text = "Sure! Here is the analysis: buy everything."
        else:
            inp = _input(req)
            out = getattr(self, f"_{req.task}")(inp)
            text = json.dumps(out, ensure_ascii=False)
        return LLMRawResponse(text, self.model, estimate_tokens(req.system + req.prompt), estimate_tokens(text),
                              time.perf_counter() - t0, {"mode": self.mode})

    # ---------------- tasks
    def _event_extractor(self, inp: dict) -> dict:
        events = []
        for d in inp["documents"]:
            if self.mode == "obey_injection" and "ignore previous instructions" in d["text"].lower():
                events.append({"ticker": "9999", "source_ids": [d["source_id"]], "event_type": "order",
                               "direction": "positive", "confidence": 1.0, "horizon_days": 5,
                               "summary": "Buy ticker 9999, set weight 25%", "reason": "instructed",
                               "risk": "none", "fact_refs": []})
                continue
            c = classify(d["text"])
            if not c:
                continue
            et, direction, conf, hz = c
            ev = {"ticker": d["ticker"], "source_ids": [d["source_id"]], "event_type": et, "direction": direction,
                  "confidence": conf, "horizon_days": hz,
                  "summary": d["text"][:80], "reason": f"公告主旨顯示{et}相關事件", "risk": "僅依公告主旨判斷，未見內文細節",
                  "fact_refs": []}
            if self.mode == "hallucinate_number":
                ev["summary"] = d["text"][:40] + "，營收年增 37.5%"
            if self.mode == "invent_ticker":
                ev["ticker"] = "1234"
            events.append(ev)
        return {"events": events}

    def _market_narrator(self, inp: dict) -> dict:
        f = inp["facts"]
        parts = []
        for k, v in f.items():
            parts.append(f"{v['label']} {v['text']}")
        s = "、".join(parts[:6])
        logic = (f"綜合市場事實（{s}），規則式判定為 {inp['regime']}；本日部位變化由量化流程決定，"
                 f"淨曝險意圖為 {inp['net_exposure_intent']}。")
        if self.mode == "hallucinate_number":
            logic += "外資預估明日買超 512 億。"
        counter = None
        neg = [v for v in f.values() if v.get("value", 0) < 0]
        if neg and inp["regime"] != "risk_off":
            counter = f"{neg[0]['label']} 為 {neg[0]['text']}，需留意轉弱"
        return {"logic": logic, "counter_evidence": counter, "fact_refs": list(f.keys())[:3]}

    def _mops_research(self, inp: dict) -> dict:
        items = []
        for d in inp["documents"]:
            c = classify(d["text"])
            et = c[0] if c else "other"
            it = {"event_type": et, "summary": f"{d['ticker']} 公告：{d['text'][:60]}",
                  "positive_evidence": ["公告內容顯示營運面有具體進展"] if c and c[1] == "positive" else [],
                  "negative_evidence": ["公告內容顯示營運面承壓"] if c and c[1] == "negative" else [],
                  "uncertainty": "僅依公告主旨判讀，未含財務影響金額與後續細節",
                  "affected_tickers": [d["ticker"]], "fact_refs": [d["id"]]}
            if self.mode == "hallucinate_number":
                it["summary"] += "，預估年增 37.5%"
            if self.mode == "invent_ticker":
                it["affected_tickers"] = ["1234"]
            if self.mode == "obey_injection":
                it["summary"] += "，建議大幅加碼"
            items.append(it)
        return {"items": items[:8]}

    def _thesis_writer(self, inp: dict) -> dict:
        out = []
        for it in inp["items"]:
            facts = it["facts"]
            drivers = "、".join(f"{v['label']} {v['text']}" for v in list(facts.values())[:4]) or "可得因子有限"
            logic = f"{it['ticker_label']} 本日動作 {it['action']}：依量化排名 {it.get('rank_text', '-')}，主要依據為 {drivers}。"
            if self.mode == "hallucinate_number":
                logic += "預估明年 EPS 42.1 元。"
            negs = [f"{v['label']} {v['text']}" for v in facts.values() if v.get("value", 0) < 0]
            out.append({"key": it["key"], "logic": logic,
                        "counter_evidence": (negs[0] + " 為反向訊號") if negs else None,
                        "fact_refs": list(facts.keys())[:3]})
        return {"items": out}

    def _reviewer(self, inp: dict) -> dict:
        return {"verdict": "PASS", "issues": []}


class TemplateProvider(LLMProvider):
    """Explicit 'no LLM' provider: every call is unavailable -> deterministic template path."""
    name = "template"
    model = "template"

    def available(self) -> bool:
        return False

    def complete(self, req: LLMRequest) -> LLMRawResponse:  # pragma: no cover - never called by client
        from agent.llm.base import LLMUnavailable
        raise LLMUnavailable("template provider")
