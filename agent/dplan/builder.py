"""Build the Evidence Graph for one trade date (quant-only, deterministic templates).

Every number written into a text field is formatted from a Fact/Signal node value; no number
is invented. LLM writers (agent.llm.interfaces) can later replace the template text only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from agent.config import D
from agent.dplan.funding import derive_funding
from agent.dplan.graph import EvidenceGraph
from agent.dplan.posture import derive_posture
from agent.engine.orders import orders_to_dplan
from agent.engine.rules import RuleBook
from agent.llm.interfaces import TemplateMarketNarrator, TemplateThesisWriter


@dataclass
class SourceInfo:
    key: str
    authority: str
    url: str
    name: str
    content_as_of: str
    fetched_at: str | None = None
    published_at: str | None = None
    archive_url: str | None = None


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x)) and not pd.isna(x)


def ticker_fact_values(row: pd.Series) -> dict[str, float]:
    """Numeric, publicly verifiable facts for one ticker (values only numbers)."""
    m = {
        "close_prev": ("close_prev", 1, 2),
        "ret_20d_pct": ("ret_20d", 100, 2),
        "ret_60d_pct": ("ret_60d", 100, 2),
        "rs_20d_vs_median_pct": ("relative_strength_20d", 100, 2),
        "dist_52w_high_pct": ("distance_to_52w_high", 100, 2),
        "volatility_20d_ann_pct": ("volatility_20d", 100, 1),
        "inst_net_5d_lots": ("inst_net_5d_shares", 0.001, 0),
        "inst_net_20d_lots": ("inst_net_20d_shares", 0.001, 0),
        "revenue_yoy_pct": ("revenue_yoy", 100, 1),
        "revenue_mom_pct": ("revenue_mom", 100, 1),
    }
    out = {}
    for k, (col, mult, nd) in m.items():
        v = row.get(col)
        if _ok(v):
            out[k] = round(float(v) * mult, nd) if nd else float(round(float(v) * mult))
    return out


def build_graph(trade_date: str, fs, scores: pd.DataFrame, result, prev_holdings: dict[str, int],
                prev_cash, nav_prev, closes_prev: dict, rb: RuleBook, cfg: dict,
                sources: dict[str, SourceInfo], narrator=None, writer=None,
                events: list | None = None, signal_audit: dict | None = None) -> tuple[EvidenceGraph, dict]:
    """events: EventFact list (already validated/grounded); signal_audit: ticker -> fusion audit dict."""
    narrator = narrator or TemplateMarketNarrator()
    writer = writer or TemplateThesisWriter()
    g = EvidenceGraph(trade_date)
    f = fs.features
    nav_prev = D(nav_prev)
    for s in sources.values():
        g.add("Source", s.key, {"authority": s.authority, "url": s.url, "name": s.name,
                                "content_as_of": s.content_as_of, "fetched_at": s.fetched_at,
                                "published_at": s.published_at, "archive_url": s.archive_url})

    px_src = [k for k in ("src:twse_px", "src:tpex_px") if k in sources]
    # ---- market facts
    mk = fs.market
    mvals = {"breadth_above_ma20_pct": round(mk.get("breadth_above_ma20", float("nan")) * 100, 1),
             "advancers_1d": mk.get("advancers_1d"), "decliners_1d": mk.get("decliners_1d"),
             "median_ret_1d_pct": round(mk.get("universe_median_ret_1d", float("nan")) * 100, 2),
             "median_ret_5d_pct": round(mk.get("universe_median_ret_5d", float("nan")) * 100, 2),
             "median_ret_20d_pct": round(mk.get("universe_median_ret_20d", float("nan")) * 100, 2)}
    mvals = {k: v for k, v in mvals.items() if _ok(v)}
    if not mvals:
        mvals = {"n_with_price": mk.get("n_with_price", 0)}
    g.add("Fact", "fact:market", {"topic": "tw_market_breadth", "values": mvals,
                                  "statement": narrator.market_fact_statement(mvals, fs.last_data_date)},
          refs=px_src)
    mkt_facts = ["fact:market"]
    ov = {"overnight_sp500_ret": ("sp500_ret_pct", "src:us_overnight"), "overnight_nasdaq_ret": ("nasdaq100_ret_pct", "src:us_overnight"),
          "overnight_sox_ret": ("sox_ret_pct", "src:us_overnight"), "tsm_adr_ret": ("tsm_adr_ret_pct", "src:us_overnight"),
          "taiex_futures_night_ret": ("txf_night_ret_pct", "src:taifex_night"), "usd_twd_ret": ("usdtwd_ret_pct", "src:fx")}
    ovals, orefs = {}, []
    for k, (name, src) in ov.items():
        if _ok(mk.get(k)) and src in sources:
            ovals[name] = round(float(mk[k]) * 100, 2)
            if src not in orefs:
                orefs.append(src)
    if ovals:
        g.add("Fact", "fact:overnight", {"topic": "overnight", "values": ovals,
                                         "statement": narrator.overnight_statement(ovals)}, refs=orefs)
        mkt_facts.append("fact:overnight")

    def ticker_fact(t: str) -> str:
        key = f"fact:{t}"
        if key in g.nodes:
            return key
        row = f.loc[t] if t in f.index else pd.Series(dtype=float)
        vals = ticker_fact_values(row)
        mkt = rb.universe[t]["market"]
        refs = ["src:twse_px" if mkt == "TWSE" else "src:tpex_px"]
        if any(k.startswith("inst_") for k in vals):
            refs.append("src:twse_inst" if mkt == "TWSE" else "src:tpex_inst")
        if any(k.startswith("revenue_") for k in vals) and "src:revenue" in sources:
            refs.append("src:revenue")
        refs = [r for r in refs if r in sources]
        if not vals:
            vals = {"close_prev": float(D(closes_prev[t]))} if t in closes_prev else {"no_data": 0}
        g.add("Fact", key, {"ticker": t, "topic": "stock_quant", "values": vals,
                            "statement": writer.fact_statement(t, rb.universe[t]["name"], vals, fs.last_data_date)},
              refs=refs)
        return key

    info: dict = {"fallback": bool(getattr(result, "is_fallback", False))}
    prev_h = {t: int(s) for t, s in prev_holdings.items() if int(s) > 0}

    if info["fallback"]:
        reason = result.reason
        orders = []
        decisions = []
        nt = sorted(prev_h)
        regime, stance, why, cash_rng = "neutral", "defensive", "組合建構未通過合規，維持前日組合", (0.0, 0.25)
        fkeys = [ticker_fact(t) for t in nt] or ["fact:market"]
        chunks = [fkeys[i:i + 10] for i in range(0, len(fkeys), 10)]
        for ci, ch in enumerate(chunks):
            g.add("Inference", f"inf:fallback:{ci}", {"logic": writer.fallback_logic(reason),
                                                      "counter_evidence": None, "tickers": nt[ci * 10:(ci + 1) * 10]},
                  refs=ch)
        for i, t in enumerate(nt):
            g.add("NoTrade", f"nt:{t}", {"ticker": t, "reason": "維持前日組合（fallback）"},
                  refs=[f"inf:fallback:{i // 10}"])
        sel_info = {}
    else:
        tp = result
        regime, stance, why, cash_rng = tp.regime, tp.stance, tp.regime_why, tp.cash_range
        sel_info = tp.selection
        rank_of = sel_info.get("rank_of", {})
        n_elig = len(rank_of)
        plan = tp.plan
        decisions = []
        for p in plan:
            if p.action == "NO_TRADE":
                continue
            decisions.append({"decision_id": f"dec:{p.ticker}", "ticker": p.ticker, "action": p.action,
                              "target_weight": float(p.target_weight)})
        orders = orders_to_dplan(tp.orders)
        for o in orders:
            o["decision_ref"] = f"dec:{o['ticker']}"
        info["plan"] = plan
    # posture & funding derived from orders
    post = derive_posture(orders, prev_cash, nav_prev, closes_prev, rb,
                          tuple(cfg["strategy_buffers"]["cash_declared_range"]))
    funding = derive_funding(decisions, orders, prev_cash, nav_prev, closes_prev, rb, post.target_cash_pct_range[0])
    info["posture"] = post
    info["funding"] = funding

    g.add("Signal", "sig:regime", {"regime": regime, "stance": stance, "why": why, "cash_target_range": cash_rng,
                                   "net_flow": float(post.net_flow), "nav_prev": float(nav_prev)},
          refs=mkt_facts)
    mv_logic = narrator.market_logic(dict(mvals, **ovals), regime, why, cash_rng, post)
    g.add("MarketView", "mv", {"logic": mv_logic, "regime": regime, "stance": stance,
                               "posture": {"net_exposure_intent": post.net_exposure_intent,
                                           "target_cash_pct_range": list(post.target_cash_pct_range)},
                               "counter_evidence": narrator.market_counter(mvals, regime)},
          refs=mkt_facts)

    ev_by_t: dict[str, list] = {}
    for e in sorted(events or [], key=lambda x: (-x.confidence, x.published_at)):
        if len(ev_by_t.get(e.ticker, [])) < 2:
            ev_by_t.setdefault(e.ticker, []).append(e)
    n_ev = [0]

    def event_facts(t: str) -> list[str]:
        """EventFact -> Source (mops) + Fact nodes; returns fact keys (max 2 per ticker, 16 per day)."""
        keys = []
        for e in ev_by_t.get(t, []):
            if n_ev[0] >= 16:
                break
            fk = f"event:{e.event_id}"
            if fk not in g.nodes:
                src = f"src:ev:{e.source_ids[0]}"
                if src not in g.nodes:
                    g.add("Source", src, {"authority": "mops", "url": (e.raw_refs[0] if e.raw_refs and e.raw_refs[0]
                                                                     else "https://mops.twse.com.tw/mops/#/web/t05st02"),
                                          "name": f"MOPS 重大訊息 {t}（{e.published_at[:16]}）",
                                          "content_as_of": e.published_at, "published_at": e.published_at,
                                          "fetched_at": None, "archive_url": None})
                vals = {"event_direction": float(e.sign), "event_confidence": round(e.confidence, 2),
                        "event_horizon_days": float(e.horizon_days)}
                if signal_audit and t in signal_audit:
                    vals["event_adjustment_pctile"] = round(signal_audit[t]["adjustment"] * 100, 2)
                g.add("Fact", fk, {"ticker": t, "topic": "company_event", "values": vals,
                                   "statement": f"{t} 公告事件（{e.event_type}，{e.direction}）：{e.summary}"[:500]},
                      refs=[src])
                n_ev[0] += 1
            keys.append(fk)
        return keys

    if not info["fallback"]:
        from agent.portfolio.baseline import turnover_params
        tpar = turnover_params(cfg)
        band = tpar["rebalance_threshold"]
        sc = scores["score"].to_dict() if "score" in scores else {}
        cur_w = {t: Decimal(s) * D(closes_prev[t]) / nav_prev for t, s in prev_h.items()}
        nts = [p for p in tp.plan if p.action == "NO_TRADE"]
        if hasattr(writer, "prepare"):            # LLM writer: one batched call AFTER decisions are final
            items = []
            for d in decisions:
                t = d["ticker"]
                items.append({"key": f"dec:{t}", "ticker_label": f"{t} {rb.universe[t]['name']}", "action": d["action"],
                              "rank_text": f"{rank_of.get(t)}/{n_elig}" if rank_of.get(t) else "-",
                              "fact_sets": [(t, g.get(ticker_fact(t)).data["values"])]})
            for ci in range(0, len(nts), 10):
                ch = nts[ci:ci + 10]
                items.append({"key": f"hold:{ci // 10}", "ticker_label": "、".join(p.ticker for p in ch),
                              "action": "NO_TRADE", "rank_text": "-",
                              "fact_sets": [(p.ticker, g.get(ticker_fact(p.ticker)).data["values"]) for p in ch]})
            writer.prepare(items)
        for d in decisions:
            t = d["ticker"]
            fk = ticker_fact(t)
            vals = g.get(fk).data["values"]
            evk = event_facts(t)
            ctx = {"ticker": t, "name": rb.universe[t]["name"], "action": d["action"],
                   "target_weight": d["target_weight"], "current_weight": float(cur_w.get(t, 0)),
                   "rank": rank_of.get(t), "n_eligible": n_elig, "score": sc.get(t),
                   "hold_limit": tpar["hold_rank"],
                   "funding_for": bool(funding.get(d["decision_id"])), "values": vals,
                   "events": [g.get(k).data["statement"] for k in evk]}
            g.add("Signal", f"sig:{t}", {"rank": ctx["rank"], "score": ctx["score"], "n_eligible": n_elig})
            g.add("Inference", f"inf:{t}", {"logic": writer.decision_logic(ctx),
                                            "counter_evidence": writer.counter_evidence(ctx),
                                            "conclusion": writer.conclusion(ctx)}, refs=[fk] + evk)
            ff = [k for k in funding.get(d["decision_id"], [])]
            g.add("Decision", d["decision_id"], {**d, "funding_for": ff,
                                                 "risk_check": writer.risk_check(ctx, rb)}, refs=[f"inf:{t}"])
        fkeys = [ticker_fact(p.ticker) for p in nts]
        for ci in range(0, len(nts), 10):
            ch = nts[ci:ci + 10]
            hitems = [(p.ticker, float(cur_w.get(p.ticker, 0)), float(p.target_weight), rank_of.get(p.ticker), p.reason)
                      for p in ch]
            if hasattr(writer, "hold_logic_keyed"):
                ph = "".join("{{fact:" + p.ticker + "}}" for p in ch)
                hl = writer.hold_logic_keyed(f"hold:{ci // 10}", hitems, band, ph)
            else:
                hl = writer.hold_logic(hitems, band)
            g.add("Inference", f"inf:hold:{ci // 10}", {"logic": hl, "counter_evidence": None},
                  refs=fkeys[ci:ci + 10])
            for p in ch:
                g.add("NoTrade", f"nt:{p.ticker}", {"ticker": p.ticker,
                                                    "reason": writer.no_trade_reason(p.reason, band)},
                      refs=[f"inf:hold:{ci // 10}"])
        for d in decisions:
            for ref in g.get(d["decision_id"]).data["funding_for"]:
                if ref not in g.nodes:
                    raise KeyError(ref)
    for o in orders:
        g.add("Order", f"ord:{o['ticker']}", o, refs=[o["decision_ref"]])
    return g, info
