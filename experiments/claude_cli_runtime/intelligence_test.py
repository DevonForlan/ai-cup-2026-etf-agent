"""CLI intelligence-advantage cases (no trading changes). Template baseline vs Claude CLI.
B: conflicting evidence synthesis; C: several MOPS-like unstructured announcements (SYNTHETIC test texts).
Case A (pure daily narrative) is covered by the 3 / 15-day replays (template vs CLI on real W5 days).
Output: results/intelligence_test.json + results/intelligence_side_by_side.md for human review."""
import json
import sys

from _common import OUT, call, grounded, grounding, provider, write

CASE_B = {"facts": {
    "F1": {"statement": "2330 九月營收年增 35.2%，創同期新高", "values": {"rev_yoy_pct": 35.2}},
    "F2": {"statement": "外資連續 5 日賣超 2330，累計 41,200 張", "values": {"days": 5, "net_sell_lots": 41200}},
    "F3": {"statement": "2330 20 日報酬 +12.4%，站上 20 日均線", "values": {"ret_20d_pct": 12.4}},
    "F4": {"statement": "費城半導體指數隔夜 -2.10%", "values": {"sox_pct": -2.1}},
    "F5": {"statement": "2330 現權重 9.80%，量化評分排名第 3", "values": {"w": 9.8, "rank": 3}}},
    "quant_decision": {"ticker": "2330", "action": "NO_TRADE", "regime": "neutral", "posture": "hold"}}

CASE_C = {"facts": {
    "D1": {"statement": "[公告 SYNTHETIC-1] 本公司董事會決議通過 2026 年第三季現金股利每股新台幣 3.5 元，除息基準日另行公告。"},
    "D2": {"statement": "[公告 SYNTHETIC-2] 本公司 2026 年 9 月合併營收新台幣 12.3 億元，較去年同期增加 18.2%，"
                        "較上月減少 4.1%，主因部分客戶拉貨遞延。"},
    "D3": {"statement": "[公告 SYNTHETIC-3] 針對媒體報導本公司第四季訂單將倍增一事，本公司澄清該報導係媒體推測，"
                        "本公司未曾發布相關財務預測。"},
    "D4": {"statement": "[公告 SYNTHETIC-4] 本公司代子公司公告取得機器設備，交易總金額新台幣 2.1 億元。"}},
    "quant_decision": {"ticker": "9999-SYNTHETIC", "action": "NO_TRADE"}}

SCHEMA_C = {"type": "object", "additionalProperties": False,
            "properties": {"events": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"doc_id": {"type": "string"},
                               "event_type": {"enum": ["dividend", "revenue", "clarification", "capex", "other"]},
                               "summary": {"type": "string"}, "sentiment": {"enum": ["positive", "negative", "neutral", "mixed"]}},
                "required": ["doc_id", "event_type", "summary", "sentiment"]}},
                "overall": {"type": "string"}, "uncertain_points": {"type": "string"},
                "fact_refs": {"type": "array", "items": {"type": "string"}}},
            "required": ["events", "overall", "uncertain_points", "fact_refs"]}


def template_baseline(payload: dict) -> str:
    """What the deterministic template can do: restate facts in order (no synthesis)."""
    return "；".join(f"{k}：{v['statement']}" for k, v in payload["facts"].items()) + "。"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = provider()
    p.schema_overrides["mops"] = SCHEMA_C
    res = {}
    rb = call(p, CASE_B, system="Synthesize the conflicting evidence about 2330 for the market_view and "
                                "counter_evidence; explain why the quant decision is NO_TRADE without changing it.")
    rc = call(p, CASE_C, task="mops", system="Classify each announcement, summarise it in Traditional Chinese, "
                                             "and state the overall picture and the uncertain points.")
    for name, payload, r in (("B_conflicting_evidence", CASE_B, rb), ("C_mops_announcements", CASE_C, rc)):
        row = {"ok": r["ok"], "latency": round(r["latency"], 2), "category": r.get("category"),
               "template": template_baseline(payload)}
        if r["ok"]:
            obj = json.loads(r["text"])
            g = grounding(payload, obj)
            row.update(output=obj, grounding=g, grounded=grounded(g))
        res[name] = row
        print(name, row["ok"], row.get("grounded"), row["latency"], json.dumps(row.get("grounding"), ensure_ascii=False))
    write("intelligence_test", res)
    md = ["# CLI intelligence-advantage cases — side by side (for human review)", "",
          "> AI 產生內容，需人工審閱。案例 C 為合成（SYNTHETIC）公告文字。", ""]
    for name, row in res.items():
        md += [f"## {name}", "", "**Template baseline**", "", row["template"], "", "**Claude Code CLI**", "",
               "```json", json.dumps(row.get("output"), ensure_ascii=False, indent=1), "```", "",
               f"grounding: {row.get('grounding')}", ""]
    (OUT / "intelligence_side_by_side.md").write_text("\n".join(md), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
