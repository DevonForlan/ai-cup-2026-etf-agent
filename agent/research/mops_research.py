"""Round 07 Research Narrative Pipeline.

MOPS / public disclosures -> Python normalize (MOPS-001..) -> LLM (one batched call) ->
event_type / summary / positive & negative evidence / uncertainty / affected_tickers / fact_refs ->
deterministic grounding -> evidence graph.

Graph rule: the MOPS document is the SOURCE FACT (raw announcement subject, written by code); the LLM
interpretation is an INFERENCE that references it. The LLM is never an evidence source, and research
never changes a ticker, weight or order: it is attached only to Decision / NoTrade nodes that the quant
program already created. Any failure -> no research inference (the template D-Plan is unchanged).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from agent.llm.grounding import allowed_numbers, ungrounded_numbers
from agent.llm.schemas import ResearchItem, ResearchOut
from agent.research.reviewer import FORBIDDEN, decision_contradiction

MOPS_URL = "https://mops.twse.com.tw/mops/#/web/t05st02"


@dataclass
class ResearchDoc:
    doc_id: str             # MOPS-001 .. (prompt-local id)
    event_key: str          # material_info.event_key (stable)
    ticker: str
    published_at: str
    subject: str
    text: str
    source_url: str = ""


@dataclass
class ResearchStats:
    docs: int = 0
    returned: int = 0
    accepted: int = 0
    rejected: list[str] = field(default_factory=list)
    called: bool = False


def select_documents(view, trade_date: str, tickers: set[str], lookback_days: int = 5, max_docs: int = 8,
                     per_ticker: int = 2) -> list[ResearchDoc]:
    """PIT-visible material_info for the given tickers, newest first, capped per ticker and per day."""
    try:
        df = view.table("material_info")
    except Exception:  # noqa: BLE001
        return []
    if df is None or len(df) == 0:
        return []
    start = (pd.Timestamp(trade_date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    df = df[df["ticker"].isin(tickers) & (df["published_at"].str[:10] >= start)
            & (df["published_at"].str[:10] < trade_date)]
    df = df.sort_values(["published_at", "event_key"], ascending=[False, True])
    out, per = [], {}
    for r in df.itertuples():
        if len(out) >= max_docs:
            break
        if per.get(r.ticker, 0) >= per_ticker:
            continue
        per[r.ticker] = per.get(r.ticker, 0) + 1
        subj = str(r.subject or "").strip()
        body = str(getattr(r, "body", "") or "").strip()
        out.append(ResearchDoc("", str(r.event_key), str(r.ticker), str(r.published_at), subj[:300],
                               (subj + ("\n" + body if body else ""))[:800], str(r.source_url or "")))
    out.sort(key=lambda d: (d.published_at, d.event_key))
    for i, d in enumerate(out):
        d.doc_id = f"MOPS-{i + 1:03d}"
    return out


def build_payload(docs: list[ResearchDoc], decisions: dict[str, str], names: dict[str, str], trade_date: str) -> dict:
    tick = sorted({d.ticker for d in docs})
    return {"trade_date": trade_date,
            "allowed_tickers": tick,
            "decisions": {t: {"name": names.get(t, ""), "action": decisions.get(t, "NO_TRADE")} for t in tick},
            "documents": [{"id": d.doc_id, "ticker": d.ticker, "published_at": d.published_at[:16],
                           "text": d.text} for d in docs]}


def check_item(it: ResearchItem, payload: dict, doc_ids: set[str], decisions: dict[str, str]) -> list[str]:
    """Deterministic grounding; any problem rejects the item (never repaired)."""
    issues = []
    allowed_t = set(payload["allowed_tickers"])
    bad_t = [t for t in it.affected_tickers if t not in allowed_t]
    if bad_t:
        issues.append(f"new tickers {bad_t}")
    bad_r = [r for r in it.fact_refs if r not in doc_ids]
    if bad_r:
        issues.append(f"unknown fact ids {bad_r}")
    text = " ".join([it.summary, *it.positive_evidence, *it.negative_evidence, it.uncertainty])
    un = ungrounded_numbers(text, allowed_numbers(payload))
    if un:
        issues.append(f"ungrounded numbers {un}")
    if FORBIDDEN.search(text):
        issues.append("forbidden instruction")
    for t in it.affected_tickers:
        c = decision_contradiction(text, decisions.get(t))
        if c:
            issues.append(f"decision contradiction ({t}): {c}")
            break
    return issues


@dataclass
class Finding:
    item: ResearchItem
    docs: list[ResearchDoc]


class MOPSResearcher:
    def __init__(self, client, max_docs: int = 8, lookback_days: int = 5):
        self.client = client
        self.max_docs = max_docs
        self.lookback_days = lookback_days
        self.stats = ResearchStats()

    def run(self, docs: list[ResearchDoc], decisions: dict[str, str], names: dict[str, str],
            trade_date: str) -> list[Finding]:
        self.stats = ResearchStats(docs=len(docs))
        if not docs or self.client is None or not self.client.enabled:
            return []
        payload = build_payload(docs, decisions, names, trade_date)
        by_id = {d.doc_id: d for d in docs}
        req = self.client.request("mops_research", "mops_research_v1", payload, list(by_id))
        self.stats.called = True
        out = self.client.generate_structured(req, ResearchOut)
        if out is None:
            return []
        self.stats.returned = len(out.items)
        found = []
        for it in out.items:
            issues = check_item(it, payload, set(by_id), decisions)
            if issues:
                self.stats.rejected.append("; ".join(issues))
                continue
            found.append(Finding(it, [by_id[r] for r in dict.fromkeys(it.fact_refs)]))
        self.stats.accepted = len(found)
        return found


def _days_before(published_at: str, trade_date: str) -> float:
    return float((pd.Timestamp(trade_date) - pd.Timestamp(published_at[:10])).days)


def inference_text(it: ResearchItem) -> tuple[str, str]:
    logic = f"公告研究解讀（{it.event_type}；LLM 推論，依據所引公告）：{it.summary}"
    if it.positive_evidence:
        logic += " 正面：" + "；".join(it.positive_evidence) + "。"
    logic = logic[:1000]
    counter = ("負面：" + "；".join(it.negative_evidence) + "。 " if it.negative_evidence else "") + \
              "不確定性：" + it.uncertainty
    return logic, counter[:500]


def attach_research(g, findings: list[Finding], trade_date: str, max_inferences: int = 4,
                    max_docs: int = 8) -> list[str]:
    """Adds Source -> Fact (raw MOPS subject) -> Inference (LLM interpretation) and appends the inference
    to existing Decision / NoTrade nodes of the affected tickers. Returns the inference keys added."""
    dec_by_t = {n.data.get("ticker"): n.key for n in g.of_kind("Decision")}
    nt_by_t = {n.data.get("ticker"): n.key for n in g.of_kind("NoTrade")}
    added, n_docs = [], 0
    for f in findings:
        if len(added) >= max_inferences:
            break
        targets = [dec_by_t.get(t) or nt_by_t.get(t) for t in f.item.affected_tickers]
        targets = [k for k in targets if k]
        if not targets:
            continue
        fkeys = []
        for d in f.docs:
            fk = f"mops:{d.event_key}"
            if fk not in g.nodes:
                if n_docs >= max_docs:
                    continue
                sk = f"src:mops:{d.event_key}"
                g.add("Source", sk, {"authority": "mops", "url": d.source_url or MOPS_URL,
                                     "name": f"MOPS 重大訊息 {d.ticker}（{d.published_at[:16]}）",
                                     "content_as_of": d.published_at, "published_at": d.published_at,
                                     "fetched_at": None, "archive_url": None})
                g.add("Fact", fk, {"ticker": d.ticker, "topic": "mops_announcement",
                                   "values": {"days_before_trade_date": _days_before(d.published_at, trade_date)},
                                   "statement": f"{d.ticker} 重大訊息（{d.published_at[:16]}）：{d.subject}"[:500]},
                      refs=[sk])
                n_docs += 1
            fkeys.append(fk)
        if not fkeys:
            continue
        ik = f"inf:mops:{len(added)}"
        logic, counter = inference_text(f.item)
        g.add("Inference", ik, {"logic": logic, "counter_evidence": counter, "origin": "llm_research",
                                "affected_tickers": list(f.item.affected_tickers)}, refs=fkeys)
        for k in dict.fromkeys(targets):
            g.add(g.get(k).kind, k, refs=[ik])
        added.append(ik)
    return added
