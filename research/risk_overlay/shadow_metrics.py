"""RESEARCH-ONLY SHADOW OBSERVATION of foreign_5 / rev_3m_yoy (Factor round: INSUFFICIENT_EVIDENCE).

Runs AFTER the official Quant v1 decision and never feeds back into it: it only READS the price / feature store
and the frozen config, and writes its own files. It never touches D-Plans, orders, weights, cash, Active Share,
the paper ledger, schedulers or config/strategy_quant_v1.yaml, and no production module imports it.

For each trade date T (PIT as of T 07:00, same scoring function as Quant v1):
  A  BASE  = Quant v1 score (revenue_yoy 0.70 / revenue_mom 0.30)
  B  BASE + 0.2 x foreign_5
  C  BASE + 0.2 x rev_3m_yoy
  D  BASE + 0.2 x foreign_5 + 0.2 x rev_3m_yoy
Recorded per variant: top-25, overlap with BASE top-25, names added / removed, Spearman vs BASE, hypothetical
equal-weight top-25 return next day (VWAP T -> close T) and 5D (VWAP T -> close T+4; filled in on later runs once
the prices exist), plus the foreign_5 / rev_3m_yoy values of the affected names.
The hypothetical portfolio is an equal-weight top-25 proxy, NOT the official tiered / hold portfolio.

    .venv\\Scripts\\python.exe research\\risk_overlay\\shadow_metrics.py            # last 8 trading days (upsert)
    .venv\\Scripts\\python.exe research\\risk_overlay\\shadow_metrics.py --from 2026-09-01
Outputs: data/shadow_metrics/shadow_history.csv, reports/shadow_metrics/<date>_shadow.md
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

VARIANTS = {"B_foreign_5": {"foreign_5": 0.2}, "C_rev_3m_yoy": {"rev_3m_yoy": 0.2},
            "D_both": {"foreign_5": 0.2, "rev_3m_yoy": 0.2}}       # sign + weight fixed by the Factor round
TOP = 25
HIST = ROOT / "data" / "shadow_metrics" / "shadow_history.csv"
REP = ROOT / "reports" / "shadow_metrics"
LABEL = "RESEARCH_ONLY_SHADOW — no effect on D-Plan / BUY-SELL / weights / cash / Active Share / Quant v1"


def compute(start: str | None, end: str | None, lookback: int = 8) -> list[dict]:
    from agent.config import load_strategy
    from agent.data.loaders import HistoryStore
    from agent.engine.rules import load_rulebook
    from agent.pipeline import cached_features
    from agent.portfolio.ranking import score
    from agent.research.factor_lab import build_panels
    store = HistoryStore()
    cfg = load_strategy("config/strategy_quant_v1.yaml")            # read only
    method = cfg["baseline"]["method"]
    uni = sorted(load_rulebook().universe)
    P, _ = build_panels(store)
    px = store.load("daily_prices")
    close = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    vwap = px.pivot_table(index="date", columns="ticker", values="vwap").sort_index().reindex(close.index)
    days = list(close.index)
    sel = [d for d in days if (start is None or d >= start) and (end is None or d <= end)]
    if start is None:
        sel = sel[-lookback:]
    rows = []
    for T in sel:
        i = days.index(T)
        fs = cached_features(store, f"{T}T07:00:00+08:00", T, uni)[0]
        f = fs.features.copy()
        for k in ("foreign_5", "rev_3m_yoy"):
            f[f"cand_{k}"] = P[k].loc[T].reindex(f.index).to_numpy() if T in P[k].index else np.nan
        base = score(f, cfg["score_weights"], method)
        btop = list(base[base["eligible"]].head(TOP).index)

        def fwd(names, h):
            if i + h - 1 >= len(days):
                return np.nan
            end_d = days[i + h - 1]
            return float((close.loc[end_d, names] / vwap.loc[T, names] - 1).mean())

        def val(k, names):
            return {t: (None if pd.isna(f.at[t, f"cand_{k}"]) else round(float(f.at[t, f"cand_{k}"]), 4)) for t in names}

        rec = {"trade_date": T, "A_base_top25": json.dumps(btop), "A_base_fwd1": fwd(btop, 1), "A_base_fwd5": fwd(btop, 5),
               "A_base_mean_foreign_5": float(f.loc[btop, "cand_foreign_5"].mean()),
               "A_base_mean_rev_3m_yoy": float(f.loc[btop, "cand_rev_3m_yoy"].mean())}
        for v, extra in VARIANTS.items():
            w = dict(cfg["score_weights"], **{f"cand_{k}": x for k, x in extra.items()})
            sc = score(f, w, method)
            top = list(sc[sc["eligible"]].head(TOP).index)
            both = base.index.intersection(sc.index)
            e = base.loc[both, "eligible"] & sc.loc[both, "eligible"]
            added, removed = sorted(set(top) - set(btop)), sorted(set(btop) - set(top))
            rec.update({f"{v}_top25": json.dumps(top), f"{v}_overlap": len(set(top) & set(btop)),
                        f"{v}_added": json.dumps(added), f"{v}_removed": json.dumps(removed),
                        f"{v}_spearman": float(base.loc[both][e]["score"].rank().corr(sc.loc[both][e]["score"].rank())),
                        f"{v}_fwd1": fwd(top, 1), f"{v}_fwd5": fwd(top, 5),
                        f"{v}_added_values": json.dumps({k: val(k, added) for k in extra}),
                        f"{v}_removed_values": json.dumps({k: val(k, removed) for k in extra})})
            rec[f"{v}_delta_fwd1"] = rec[f"{v}_fwd1"] - rec["A_base_fwd1"]
            rec[f"{v}_delta_fwd5"] = rec[f"{v}_fwd5"] - rec["A_base_fwd5"]
        rec["fwd5_complete"] = bool(i + 4 < len(days))
        rec["label"] = LABEL
        rows.append(rec)
    return rows


def write_md(r: dict) -> Path:
    pp = lambda x: "pending" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.2f}%"  # noqa: E731
    L = [f"# Shadow Metrics — {r['trade_date']}", "", f"> **{LABEL}**。研究用，AI 產生內容，需人工審閱。", "",
         "| 變體 | top-25 重疊 | Spearman vs BASE | 新增 | 移除 | 次日（VWAP→收盤） | 5 日 | Δ次日 | Δ5 日 |",
         "|---|---|---|---|---|---|---|---|---|",
         f"| A BASE（Quant v1 排名） | 25 | 1.000 | - | - | {pp(r['A_base_fwd1'])} | {pp(r['A_base_fwd5'])} | - | - |"]
    for v in VARIANTS:
        L.append(f"| {v} | {r[f'{v}_overlap']} | {r[f'{v}_spearman']:.3f} | {', '.join(json.loads(r[f'{v}_added'])) or '-'} | "
                 f"{', '.join(json.loads(r[f'{v}_removed'])) or '-'} | {pp(r[f'{v}_fwd1'])} | {pp(r[f'{v}_fwd5'])} | "
                 f"{pp(r[f'{v}_delta_fwd1'])} | {pp(r[f'{v}_delta_fwd5'])} |")
    L += ["", f"BASE top-25 平均 foreign_5 = {r['A_base_mean_foreign_5']:.4f}，平均 rev_3m_yoy = {r['A_base_mean_rev_3m_yoy']:.4f}", "",
          "新增 / 移除個股的因子值：", ""]
    for v in VARIANTS:
        L.append(f"- {v} 新增 {r[f'{v}_added_values']}；移除 {r[f'{v}_removed_values']}")
    L += ["", "假設組合 = 等權 top-25（非正式的分級 / 持有組合）。5 日報酬在資料到齊後由下一次執行補算（fwd5_complete="
          f"{r['fwd5_complete']}）。", ""]
    REP.mkdir(parents=True, exist_ok=True)
    p = REP / f"{r['trade_date']}_shadow.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=None)
    ap.add_argument("--to", dest="end", default=None)
    a = ap.parse_args(argv)
    rows = compute(a.start, a.end)
    HIST.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(HIST, dtype={"trade_date": str}) if HIST.exists() else pd.DataFrame()
    new = pd.concat([old, pd.DataFrame(rows)]).drop_duplicates("trade_date", keep="last").sort_values("trade_date")
    new.to_csv(HIST, index=False)
    for r in rows:
        write_md(r)
    print(f"SHADOW {len(rows)} dates {rows[0]['trade_date'] if rows else '-'}..{rows[-1]['trade_date'] if rows else '-'} "
          f"history={len(new)} rows -> {HIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
