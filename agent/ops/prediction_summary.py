"""Round 08-A: human-readable DAILY_PREDICTION_SUMMARY after a PASS precompetition run.

reports/daily_predictions/<trade_date>_prediction.md — a READ-ONLY view of the FINAL candidate package
(D-Plan, orders, portfolio, scores, run summary). It is NOT a D-Plan and never changes anything.
Every file is labelled PRECOMPETITION_PAPER_RUN (not an official competition result).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "reports" / "daily_predictions"
LABEL = "PRECOMPETITION_PAPER_RUN"
ACTION_MAP = {"BUY": "BUY", "ADD": "BUY", "TRIM": "REDUCE", "SELL_ALL": "SELL"}


def _csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build(trade_date: str, ops_cfg: dict | None = None, run_summary: dict | None = None,
          run_time: str | None = None, out_dir: Path | None = None, root: Path | None = None) -> Path | None:
    from agent.engine.rules import load_rulebook
    from agent.ops.common import load_ops_config, ops_path, ymd
    from agent.ops.package_submission import active_final
    root = root or ROOT
    ops_cfg = ops_cfg or load_ops_config()
    rec = active_final(trade_date, ops_cfg)
    if rec is None:
        return None
    pkg = ops_path(ops_cfg, "submissions_dir") / ymd(trade_date) / "candidates" / rec["run_id"]
    doc = json.loads((pkg / rec["file"]).read_text(encoding="utf-8"))
    meta = json.loads((pkg / "run_metadata.json").read_text(encoding="utf-8")) if (pkg / "run_metadata.json").exists() else {}
    val = json.loads((pkg / "validation_report.json").read_text(encoding="utf-8")) if (pkg / "validation_report.json").exists() else {}
    port = _csv(pkg / "portfolio.csv")
    rb = load_rulebook()
    names = {t: v.get("name", "") for t, v in rb.universe.items()}
    s = run_summary or {}
    if not s:
        sp = ops_path(ops_cfg, "ops_logs_dir") / ymd(trade_date) / "competition_day_summary.json"
        s = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    cs = s.get("compliance_summary") or {}
    scores = {}
    sc_path = ops_path(ops_cfg, "ops_logs_dir") / ymd(trade_date) / "run" / "scores" / f"{ymd(trade_date)}.parquet"
    if sc_path.exists():
        import pandas as pd
        df = pd.read_parquet(sc_path)
        scores = {str(r.ticker): r for r in df.itertuples()}
        n_elig = int(df["eligible"].sum()) if "eligible" in df else len(df)
    else:
        n_elig = None
    mv = doc["market_view"]
    infs = {i["inf_id"]: i for i in doc.get("inferences", [])}
    start = s.get("start") or {}
    start_nav = float(start.get("nav") or 0)
    prev_close: dict[str, float] = {}
    if start.get("holdings"):
        from agent.data.loaders import HistoryStore
        px = HistoryStore().load("daily_prices")
        px = px[px["date"] == start.get("date")]
        prev_close = {str(r.ticker): float(r.close) for r in px.itertuples() if r.close == r.close}
    dec = {d["ticker"]: d for d in doc.get("decisions", [])}
    L = [f"# Daily Prediction — {trade_date}（{LABEL}）", "",
         f"> **{LABEL}** — 賽前紙上交易，**不是正式比賽成績，也不是正式 D-Plan**。不上傳、不提交。AI 產生內容，需人工審閱。", "",
         "| 項目 | 值 |", "|---|---|",
         f"| Date（產生日） | {(run_time or meta.get('generated_at') or '')[:10]} |",
         f"| Run time | {run_time or meta.get('generated_at', '-')} |",
         f"| Trade date | {trade_date} |",
         f"| Run ID | {rec['run_id']} |",
         f"| Starting point | {((s.get('settlement') or {}).get('source')) or '-'} |", "",
         "## Portfolio", "",
         "| 項目 | 值 |", "|---|---|",
         f"| Total holdings | {(s.get('portfolio') or {}).get('holdings_after', len(port))} |",
         f"| Cash weight (est.) | {float((s.get('portfolio') or {}).get('cash_ratio_est') or 0):.2%} |",
         f"| Active Share (official, top-15, NAV) | {cs.get('Active Share official >= 15%', '-')} |",
         f"| Regime / posture | {mv.get('regime')} / {(mv.get('posture') or {}).get('net_exposure_intent')} |",
         f"| Compliance | {' / '.join(f'{k}: {v}' for k, v in cs.items() if k not in ('Claude runtime',)) or '-'} |", "",
         "## Holdings", "", "| Ticker | Name | Target weight | Current weight | Action | Rank |", "|---|---|---|---|---|---|"]
    for r in sorted(port, key=lambda r: -float(r.get("target_weight") or 0)):
        t = r["ticker"]
        cur = float(r.get("current_shares") or 0) * prev_close.get(t, 0.0) / start_nav if start_nav else 0.0
        act = ACTION_MAP.get(dec[t]["action"], dec[t]["action"]) if t in dec else "HOLD"
        rk = scores.get(t)
        L.append(f"| {t} | {names.get(t, '')} | {float(r['target_weight'] or 0):.2%} | {cur:.2%} | {act} | "
                 f"{int(rk.rank) if rk is not None and rk.rank == rk.rank else '-'} |")
    L += ["", "## Orders", "", "| Ticker | Side | Shares |", "|---|---|---|"]
    L += [f"| {o['ticker']} | {o['side']} | {int(o['shares']):,} |" for o in doc.get("orders", [])] or ["| - | - | - |"]
    from agent.config import load_strategy
    sw = {k: v for k, v in load_strategy("config/strategy_quant_v1.yaml")["score_weights"].items() if v}
    top = sorted((r for r in scores.values() if r.rank == r.rank), key=lambda r: r.rank)[:5]
    L += ["", "## Quant", "",
          f"- Primary signals (frozen Quant Core v1): {', '.join(f'{k} {v}' for k, v in sw.items())}（百分位排名）",
          f"- Ranking: {n_elig if n_elig is not None else '-'} eligible；前 5 名："
          + ("、".join(f"{r.ticker} {names.get(str(r.ticker), '')}（score {r.score:.3f}）" for r in top) or "-")]
    thesis = [infs[i]["logic"] for d in doc.get("decisions", [])[:3] for i in d.get("inference_refs", [])[:1] if i in infs]
    llm = s.get("llm") or {}
    L += ["", "## Claude（敘事；不影響決策）", "",
          f"- Runtime: {'Claude CLI used' if llm.get('used') else 'Template fallback'}"
          f"（calls {llm.get('calls', 0)}, failed {llm.get('failed', 0)}, research inferences {llm.get('research_inferences', 0)}）",
          f"- **Market view**: {mv.get('logic', '-')}",
          f"- **Counter evidence / major risk**: {mv.get('counter_evidence') or '-'}",
          "- **Portfolio thesis (前 3 筆決策)**:"] + [f"  - {t[:300]}" for t in thesis]
    L += ["", "## D-Plan", "",
          f"- Version: {doc.get('schema_version')}",
          f"- Validation: {'PASS' if val.get('ok') else 'FAIL'}（{val.get('summary', '')}）",
          f"- Final candidate: `{rec['path']}`（sha256 {rec['sha256'][:23]}…）",
          f"- Decision fingerprint: {meta.get('decision_fingerprint', '-')}", "",
          f"## Overall: **{'READY' if val.get('ok') and s.get('status') in ('DRY_RUN_OK', 'READY_TO_SUBMIT', None) else 'BLOCKED'}**", ""]
    out_dir = out_dir or OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{trade_date}_prediction.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p
