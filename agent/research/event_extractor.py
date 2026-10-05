"""Phase 5A — grounded Event Extractor.

Input : PIT-visible company announcements (material_info) + program-provided facts.
Output: EventFact list. The LLM may only choose tickers / source ids / fact ids from the lists it is
given; publication time is copied from the source by code; numbers must be grounded in the input.
Invalid events are DROPPED (counted as hallucinations), never repaired, never turned into free text.

BLIND mode (backtests on data the model may have seen in pre-training): tickers -> SEC###, company
names removed, dates -> "Day T", source ids -> DOC#. The mapping is reversed by code.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from agent.config import ROOT
from agent.llm.client import LLMClient
from agent.llm.grounding import allowed_numbers, bad_refs, ungrounded_numbers
from agent.llm.schemas import EventItem, EventsOut
from agent.research.reviewer import FORBIDDEN

DATE_RE = re.compile(r"(\d{2,4})[/\-.年](\d{1,2})[/\-.月](\d{1,2})日?")


@dataclass
class RawDoc:
    source_id: str          # material_info.event_key
    ticker: str
    published_at: str       # ISO +08:00 (from source)
    text: str
    source_url: str = ""
    authority: str = "mops"


@dataclass
class EventFact:
    event_id: str           # fingerprint
    ticker: str
    event_type: str
    direction: str
    confidence: float
    horizon_days: int
    published_at: str
    source_ids: list[str]
    summary: str
    reason: str
    risk: str
    raw_refs: list[str]     # source urls
    fact_refs: list[str] = field(default_factory=list)
    extractor: str = ""     # provider/model/prompt_version

    @property
    def sign(self) -> int:
        return {"positive": 1, "negative": -1}.get(self.direction, 0)


@dataclass
class ExtractionStats:
    documents: int = 0
    calls: int = 0
    events_raw: int = 0
    events_kept: int = 0
    dropped_ticker: int = 0
    dropped_source: int = 0
    dropped_number: int = 0
    dropped_fact_ref: int = 0
    dropped_injection: int = 0
    duplicates: int = 0
    schema_failures: int = 0

    @property
    def hallucinations(self) -> int:
        return (self.dropped_ticker + self.dropped_source + self.dropped_number + self.dropped_fact_ref
                + self.dropped_injection)


def fingerprint(ticker: str, event_type: str, published_at: str, text: str) -> str:
    norm = re.sub(r"\s+", "", text)[:40]
    h = hashlib.sha256(f"{ticker}|{event_type}|{published_at[:10]}|{norm}".encode("utf-8")).hexdigest()
    return "EV_" + h[:16]


def visible_documents(view, trade_date: str, universe: set[str], lookback_days: int, max_docs: int) -> list[RawDoc]:
    """PIT documents: available_at <= as_of (PITView) and published within lookback calendar days."""
    try:
        df = view.table("material_info")
    except Exception:  # noqa: BLE001
        return []
    if df is None or len(df) == 0:
        return []
    start = (pd.Timestamp(trade_date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    df = df[df["ticker"].isin(universe) & (df["published_at"].str[:10] >= start)]
    df = df.sort_values("published_at", ascending=False).head(max_docs)
    out = []
    for r in df.itertuples():
        text = (r.subject or "") + ("\n" + r.body if getattr(r, "body", None) else "")
        out.append(RawDoc(r.event_key, r.ticker, r.published_at, text[:1500], r.source_url or "", r.authority or "mops"))
    return out


def revenue_facts(features: pd.DataFrame, tickers: list[str]) -> dict[str, dict]:
    """Program-computed facts the model may cite: FACT_<ticker>_REV_YOY / _REV_MOM (percent)."""
    facts = {}
    for t in tickers:
        if t not in features.index:
            continue
        for col, tag, label in (("revenue_yoy", "REV_YOY", "最新月營收年增率"), ("revenue_mom", "REV_MOM", "最新月營收月增率")):
            v = features.at[t, col] if col in features else np.nan
            if pd.notna(v):
                val = round(float(v) * 100, 1)
                facts[f"FACT_{t}_{tag}"] = {"ticker": t, "label": label, "value": val, "text": f"{val:+.1f}%"}
    return facts


class _Blinder:
    def __init__(self, tickers: list[str], names: dict[str, str], enabled: bool):
        self.enabled = enabled
        self.t2a = {t: f"SEC{i + 1:03d}" for i, t in enumerate(sorted(tickers))}
        self.a2t = {v: k for k, v in self.t2a.items()}
        self.names = names

    def tick(self, t: str) -> str:
        return self.t2a.get(t, t) if self.enabled else t

    def untick(self, a: str) -> str:
        return self.a2t.get(a, a) if self.enabled else a

    def text(self, s: str) -> str:
        if not self.enabled:
            return s
        for t, a in self.t2a.items():
            s = s.replace(t, a)
            nm = self.names.get(t)
            if nm and len(nm) >= 2:
                s = s.replace(nm, a)
        return DATE_RE.sub("Day T", s)


class EventExtractor:
    def __init__(self, client: LLMClient, universe: dict[str, dict], cache_dir: Path | None = None,
                 batch_size: int = 20, blind: bool | None = None):
        self.client = client
        self.universe = universe
        self.batch_size = batch_size
        self.blind = bool(client.cfg.get("blind_mode", False)) if blind is None else blind
        self.cache_dir = cache_dir
        self.stats = ExtractionStats()

    def _cache_path(self, doc: RawDoc) -> Path | None:
        if not self.cache_dir:
            return None
        tag = f"{self.client.provider_name}_{self.client.model_version}_{'blind' if self.blind else 'normal'}"
        return self.cache_dir / re.sub(r"[^A-Za-z0-9_.-]", "_", tag) / f"{doc.source_id.replace(':', '_')}.json"

    def extract(self, docs: list[RawDoc], facts: dict[str, dict]) -> list[EventFact]:
        self.stats.documents += len(docs)
        if not docs or not self.client.enabled:
            return []
        events: list[EventFact] = []
        todo = []
        for d in docs:
            p = self._cache_path(d)
            cached = None
            if p and p.exists():
                try:                                   # tolerate a concurrent/partial write -> cache miss
                    cached = [EventFact(**e) for e in json.loads(p.read_text(encoding="utf-8"))]
                except (json.JSONDecodeError, TypeError, OSError):
                    cached = None
            if cached is not None:
                events += cached
            else:
                todo.append(d)
        for i in range(0, len(todo), self.batch_size):
            batch = todo[i:i + self.batch_size]
            got = self._extract_batch(batch, facts)
            by_doc: dict[str, list] = {d.source_id: [] for d in batch}
            for e in got or []:
                by_doc.setdefault(e.source_ids[0], []).append(e)
            for d in batch:
                p = self._cache_path(d)
                if p and got is not None:
                    import os
                    p.parent.mkdir(parents=True, exist_ok=True)
                    tmp = p.with_suffix(f".tmp{os.getpid()}")
                    tmp.write_text(json.dumps([asdict(e) for e in by_doc.get(d.source_id, [])], ensure_ascii=False),
                                   encoding="utf-8")
                    try:
                        os.replace(tmp, p)             # atomic
                    except PermissionError:
                        tmp.unlink(missing_ok=True)
            events += got or []
        # dedupe (same ticker/type/day/text from several sources)
        seen, out = set(), []
        for e in sorted(events, key=lambda x: (x.published_at, x.event_id)):
            if e.event_id in seen:
                self.stats.duplicates += 1
                continue
            seen.add(e.event_id)
            out.append(e)
        self.stats.events_kept += len(out)
        return out

    def _extract_batch(self, docs: list[RawDoc], facts: dict[str, dict]) -> list[EventFact] | None:
        tickers = sorted({d.ticker for d in docs})
        names = {t: self.universe.get(t, {}).get("name", "") for t in tickers}
        bl = _Blinder(tickers, names, self.blind)
        sid = {f"DOC{i + 1}": d for i, d in enumerate(docs)}
        rel_facts = {k: v for k, v in facts.items() if v["ticker"] in tickers}
        fid = {}
        for k, v in rel_facts.items():
            fid[k.replace(v["ticker"], bl.tick(v["ticker"])) if self.blind else k] = (k, v)
        payload = {
            "allowed_tickers": [bl.tick(t) for t in tickers],
            "documents": [{"source_id": s, "ticker": bl.tick(d.ticker),
                           "published": "Day T" if self.blind else d.published_at, "text": bl.text(d.text)}
                          for s, d in sid.items()],
            "facts": {k: {"ticker": bl.tick(v["ticker"]), "label": v["label"], "value": v["value"], "text": v["text"]}
                      for k, (_, v) in fid.items()},
        }
        allowed_nums = allowed_numbers(payload)
        req = self.client.request("event_extractor", "event_extractor_v1", payload, list(rel_facts))
        self.stats.calls += 1
        out = self.client.generate_structured(req, EventsOut)
        if out is None:
            self.stats.schema_failures += 1
            return None
        kept = []
        for ev in out.events:
            self.stats.events_raw += 1
            k = self._validate(ev, payload, sid, fid, allowed_nums)
            if k is None:
                continue
            doc = sid[ev.source_ids[0]]
            ticker = bl.untick(ev.ticker)
            kept.append(EventFact(
                event_id=fingerprint(ticker, ev.event_type, doc.published_at, doc.text),
                ticker=ticker, event_type=ev.event_type, direction=ev.direction,
                confidence=float(ev.confidence), horizon_days=int(ev.horizon_days),
                published_at=doc.published_at,                          # from source, never from the model
                source_ids=[sid[s].source_id for s in ev.source_ids],
                summary=self._unblind_text(ev.summary, bl), reason=self._unblind_text(ev.reason, bl),
                risk=self._unblind_text(ev.risk, bl), raw_refs=[sid[s].source_url for s in ev.source_ids],
                fact_refs=[fid[f][0] for f in ev.fact_refs],
                extractor=f"{self.client.provider_name}/{self.client.model_version}/{req.prompt_version}"
                          + ("/blind" if self.blind else "")))
        return kept

    @staticmethod
    def _unblind_text(s: str, bl: _Blinder) -> str:
        if not bl.enabled:
            return s
        for a, t in bl.a2t.items():
            s = s.replace(a, t)
        return s

    def _validate(self, ev: EventItem, payload, sid, fid, allowed_nums) -> bool | None:
        if ev.ticker not in payload["allowed_tickers"]:
            self.stats.dropped_ticker += 1
            return None
        if bad_refs(ev.source_ids, set(sid)):
            self.stats.dropped_source += 1
            return None
        doc_tickers = {d["ticker"] for d in payload["documents"] if d["source_id"] in ev.source_ids}
        if ev.ticker not in doc_tickers:                 # event must be about the cited document's company
            self.stats.dropped_ticker += 1
            return None
        if bad_refs(ev.fact_refs, set(fid)):
            self.stats.dropped_fact_ref += 1
            return None
        if ungrounded_numbers(" ".join([ev.summary, ev.reason, ev.risk]), allowed_nums):
            self.stats.dropped_number += 1
            return None
        if FORBIDDEN.search(" ".join([ev.summary, ev.reason, ev.risk])):
            self.stats.dropped_injection += 1          # instruction-like text echoed from untrusted input
            return None
        return True


def event_scores(events: list[EventFact], trade_date: str, min_conf: float, decay: str = "linear") -> dict[str, dict]:
    """Per-ticker event score in [-1, 1] at trade_date: Σ sign × confidence × decay(age), clipped.
    age = business days between publication date and trade_date (published after T-1 close counts age 0)."""
    out: dict[str, dict] = {}
    t = np.datetime64(trade_date)
    for e in events:
        if e.confidence < min_conf or e.sign == 0:
            continue
        pub = np.datetime64(e.published_at[:10])
        if pub > t:
            continue                                   # defensive: never use future events
        age = int(np.busday_count(pub, t))
        if age >= e.horizon_days:
            continue
        w = (1 - age / e.horizon_days) if decay == "linear" else float(np.exp(-3 * age / e.horizon_days))
        d = out.setdefault(e.ticker, {"score": 0.0, "events": []})
        d["score"] += e.sign * e.confidence * w
        d["events"].append(e.event_id)
    for d in out.values():
        d["score"] = max(-1.0, min(1.0, d["score"]))
    return out
