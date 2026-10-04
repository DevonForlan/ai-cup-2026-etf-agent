"""LLM role interfaces (provider-agnostic) + deterministic Template providers.

MVP-0 uses only the Template* classes: text is assembled from Fact values, never invented.
Phase 5 will add provider implementations (Gemini / OpenAI / Claude / ...) that implement the
same Protocols and may only rewrite TEXT; refs and numbers stay controlled by code.
"""
from __future__ import annotations

from typing import Protocol

from agent.llm.schemas import ExtractedEvent, ReviewResult


class EventExtractor(Protocol):
    def extract(self, text: str, published_at: str, allowed_tickers: list[str]) -> list[ExtractedEvent]: ...


class MarketNarrator(Protocol):
    def market_fact_statement(self, values: dict, data_date: str | None) -> str: ...
    def market_logic(self, values: dict, regime: str, why: str, cash_range, posture) -> str: ...
    def market_counter(self, values: dict, regime: str) -> str | None: ...


class ThesisWriter(Protocol):
    def fact_statement(self, ticker: str, name: str, values: dict, data_date: str | None) -> str: ...
    def decision_logic(self, ctx: dict) -> str: ...
    def counter_evidence(self, ctx: dict) -> str | None: ...
    def conclusion(self, ctx: dict) -> str: ...
    def risk_check(self, ctx: dict, rb) -> str: ...
    def hold_logic(self, items: list, band: float) -> str: ...
    def no_trade_reason(self, reason: str, band: float) -> str: ...
    def fallback_logic(self, reason: str) -> str: ...


class Reviewer(Protocol):
    def review(self, dplan: dict) -> ReviewResult: ...


class NotConfiguredEventExtractor:
    def extract(self, text, published_at, allowed_tickers):
        raise NotImplementedError("EventExtractor not configured in MVP-0 (Phase 5)")


class NullReviewer:
    def review(self, dplan: dict) -> ReviewResult:
        return ReviewResult(ok=True, issues=[], reviewer="null")


def _pct(v, nd=1) -> str:
    return f"{v:+.{nd}f}%"


class TemplateMarketNarrator:
    def market_fact_statement(self, v: dict, data_date: str | None) -> str:
        parts = []
        if "breadth_above_ma20_pct" in v:
            parts.append(f"150 檔中站上 20 日均線比例 {v['breadth_above_ma20_pct']:.1f}%")
        if "advancers_1d" in v:
            parts.append(f"上漲 {v['advancers_1d']} 檔、下跌 {v.get('decliners_1d', 0)} 檔")
        for k, lab in (("median_ret_1d_pct", "1 日"), ("median_ret_5d_pct", "5 日"), ("median_ret_20d_pct", "20 日")):
            if k in v:
                parts.append(f"{lab}報酬中位數 {_pct(v[k], 2)}")
        return f"{data_date or ''} 收盤：" + "；".join(parts) if parts else "前一交易日 universe 價量資料"

    def overnight_statement(self, v: dict) -> str:
        lab = {"sp500_ret_pct": "S&P500", "nasdaq100_ret_pct": "Nasdaq100", "sox_ret_pct": "費城半導體 SOX",
               "tsm_adr_ret_pct": "TSM ADR", "txf_night_ret_pct": "台指期夜盤(相對前日結算)",
               "usdtwd_ret_pct": "USD/TWD"}
        return "隔夜/盤前：" + "；".join(f"{lab[k]} {_pct(x, 2)}" for k, x in v.items() if k in lab)

    def market_logic(self, v: dict, regime: str, why: str, cash_range, posture) -> str:
        nf = float(posture.net_flow)
        nav = float(posture.nav)
        return (f"依規則式市場判斷：{why}（{{{{fact:market}}}}{{{{fact:overnight}}}}）→ regime={regime}，策略目標現金 "
                f"{cash_range[0]:.0%}–{cash_range[1]:.0%}。本日委託以前日收盤價估算淨流向 {nf:+,.0f} 元"
                f"（{nf / nav:+.2%} NAV），淨曝險意圖 {posture.net_exposure_intent}；預估委託後現金比 "
                f"{float(posture.cash_ratio_no_fee):.2%}。")

    def market_counter(self, v: dict, regime: str) -> str | None:
        if regime == "risk_on" and v.get("median_ret_5d_pct", 0) < 0:
            return f"5 日報酬中位數 {_pct(v['median_ret_5d_pct'], 2)} 轉弱，若延續將降級為 neutral"
        if regime == "risk_off" and v.get("median_ret_1d_pct", 0) > 0:
            return f"前一日報酬中位數 {_pct(v['median_ret_1d_pct'], 2)} 反彈，若廣度回升將升級為 neutral"
        if "decliners_1d" in v and v.get("decliners_1d", 0) > v.get("advancers_1d", 0):
            return f"前一交易日下跌 {v['decliners_1d']} 檔多於上漲 {v.get('advancers_1d', 0)} 檔"
        return None


class TemplateThesisWriter:
    def fact_statement(self, t: str, name: str, v: dict, data_date: str | None) -> str:
        p = [f"{t} {name} {data_date or ''} 收盤 {v['close_prev']:,}" if "close_prev" in v else f"{t} {name}"]
        if "ret_20d_pct" in v: p.append(f"20 日報酬 {_pct(v['ret_20d_pct'])}")
        if "ret_60d_pct" in v: p.append(f"60 日報酬 {_pct(v['ret_60d_pct'])}")
        if "rs_20d_vs_median_pct" in v: p.append(f"20 日相對 universe 中位數 {_pct(v['rs_20d_vs_median_pct'])}")
        if "dist_52w_high_pct" in v: p.append(f"距 52 週高點 {_pct(v['dist_52w_high_pct'])}")
        if "inst_net_5d_lots" in v: p.append(f"近 5 日三大法人淨買賣超 {v['inst_net_5d_lots']:+,.0f} 張")
        if "revenue_yoy_pct" in v: p.append(f"最新月營收年增 {_pct(v['revenue_yoy_pct'])}")
        if "volatility_20d_ann_pct" in v: p.append(f"20 日年化波動 {v['volatility_20d_ann_pct']:.1f}%")
        return "；".join(p)

    def _drivers(self, v: dict) -> str:
        d = []
        if "ret_20d_pct" in v: d.append(f"20 日報酬 {_pct(v['ret_20d_pct'])}")
        if "rs_20d_vs_median_pct" in v: d.append(f"相對強弱 {_pct(v['rs_20d_vs_median_pct'])}")
        if "inst_net_5d_lots" in v: d.append(f"5 日法人 {v['inst_net_5d_lots']:+,.0f} 張")
        if "revenue_yoy_pct" in v: d.append(f"營收年增 {_pct(v['revenue_yoy_pct'])}")
        return "、".join(d) if d else "可得量化因子有限"

    def decision_logic(self, c: dict) -> str:
        v, a = c["values"], c["action"]
        rk = f"量化綜合評分排名 {c['rank']}/{c['n_eligible']}" if c.get("rank") else "未列入合格排名"
        base = f"{rk}（{self._drivers(v)}；{{{{fact:{c['ticker']}}}}}）。"
        if a == "BUY":
            s = base + f"符合本 ETF 動能＋籌碼＋營收之多因子選股規則，新建部位至目標權重 {c['target_weight']:.2%}。"
        elif a == "ADD":
            s = base + f"續列入選股名單，依分層權重由 {c['current_weight']:.2%} 加碼至 {c['target_weight']:.2%}。"
        elif a == "TRIM":
            s = base + f"依分層權重與上限由 {c['current_weight']:.2%} 減碼至 {c['target_weight']:.2%}。"
        else:
            s = base + (f"排名超出續抱範圍（前 {c['hold_limit']} 名）或被更高分標的替換，出清部位。"
                        if c.get("rank") else "已不符合合格條件（資料或流動性），出清部位。")
        if c.get("funding_for"):
            s += "此筆賣出同時支應同日買進資金缺口；選擇此檔讓位之理由為其排名/權重偏離在持股中最不具優先性。"
        return s

    def counter_evidence(self, c: dict) -> str | None:
        v = c["values"]
        if v.get("inst_net_5d_lots", 0) < 0 and c["action"] in ("BUY", "ADD"):
            return f"近 5 日三大法人淨賣超 {v['inst_net_5d_lots']:,.0f} 張"
        if v.get("volatility_20d_ann_pct", 0) > 60 and c["action"] in ("BUY", "ADD"):
            return f"20 日年化波動 {v['volatility_20d_ann_pct']:.1f}% 偏高"
        if v.get("ret_20d_pct", 0) > 0 and c["action"] in ("TRIM", "SELL_ALL"):
            return f"20 日報酬仍為 {_pct(v['ret_20d_pct'])}，減碼可能錯過延續漲勢"
        if v.get("dist_52w_high_pct", 0) < -25 and c["action"] in ("BUY", "ADD"):
            return f"距 52 週高點 {_pct(v['dist_52w_high_pct'])}，長期趨勢仍弱"
        return None

    def conclusion(self, c: dict) -> str:
        return f"{c['ticker']} {c['action']} → 目標權重 {c['target_weight']:.2%}"

    def risk_check(self, c: dict, rb) -> str:
        cap = rb.rules.max_weight(c["ticker"])
        return f"目標權重 {c['target_weight']:.2%} ≤ 官方上限 {float(cap):.0%}；委託由 derive-orders.v2 推導"

    def hold_logic(self, items: list, band: float) -> str:
        parts = []
        for t, cw, tw, rk, reason in items:
            r = f"排名 {rk}" if rk else "排名 -"
            parts.append(f"{t}（{r}，現權重 {cw:.2%}）")
        if items and all(it[4] == "no_rebalance_day" for it in items):
            return ("本日非策略再平衡日；以前日收盤價檢查現有組合之檔數、權重、現金與 Active Share 均合規，"
                    "為避免來回成本（約 0.585%）維持不動：" + "、".join(parts))
        return ("下列持股仍在續抱範圍內，且目標與現權重差距小於無交易帶 "
                f"{band:.1%} 或推導張數不變，為避免來回成本（約 0.585%）維持不動：" + "、".join(parts))

    def no_trade_reason(self, reason: str, band: float) -> str:
        return {"no_trade_band": f"權重偏離小於無交易帶 {band:.1%}",
                "same_lots": "目標權重推導張數與現持相同",
                "decision_limit": "單日決策數上限（30），本日延後調整",
                "no_rebalance_day": "非再平衡日，組合合規，維持不動",
                "min_holding": "未滿最短持有天數，維持不動",
                "odd_lot_locked": "持股含配股零股，無法以整股委託調整，維持不動"}.get(reason, "維持不動")

    def fallback_logic(self, reason: str) -> str:
        return f"本日組合建構未通過合規或資料檢查（{reason[:300]}），依預設安全機制維持前日組合不交易。"
