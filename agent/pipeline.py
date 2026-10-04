"""One trading day: settlement(T-1) -> PIT data -> features -> scores -> portfolio -> compliance
-> orders -> evidence graph -> D-Plan -> validation. Shared by run_daily.py and run_sim.py."""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from agent.config import ROOT, D
from agent.data.http import TPE
from agent.data.loaders import HistoryStore
from agent.data.manifest import read_manifest
from agent.data.pit import PITView
from agent.dplan.builder import SourceInfo, build_graph
from agent.dplan.exporter import export_dplan, write_dplan
from agent.engine.models import Report, Status
from agent.engine.rules import RuleBook
from agent.engine.validate_dplan import ValidationContext, validate_dplan
from agent.features.feature_engine import build_features, save_features
from agent.portfolio.constructor import FallbackToPreviousPortfolio, construct
from agent.portfolio.ranking import save_scores, score
from agent.sim.calendar import TradingCalendar
from agent.sim.models import DayMarket, Settlement


def code_version() -> str:
    """git:<sha> if the project is a clean git repo, else sha256 of agent/ + config/ (12 hex)."""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT, capture_output=True,
                             text=True, timeout=5)
        dirty = subprocess.run(["git", "status", "--porcelain", "agent", "config"], cwd=ROOT,
                               capture_output=True, text=True, timeout=5)
        if sha.returncode == 0 and not dirty.stdout.strip():
            return f"git:{sha.stdout.strip()}"
    except Exception:  # noqa: BLE001
        pass
    h = hashlib.sha256()
    for p in sorted(list((ROOT / "agent").rglob("*.py")) + list((ROOT / "config").glob("*.*"))):
        if "__pycache__" in p.parts:
            continue
        h.update(str(p.relative_to(ROOT)).replace("\\", "/").encode())
        h.update(p.read_bytes())
    return "pkg-sha256:" + h.hexdigest()[:12]


def etf_holdings_from_view(view: PITView) -> tuple[dict, dict]:
    df = view.etf_holdings()
    if len(df) == 0:
        return {}, {}
    last = df.groupby("etf")["date"].max()
    out = {}
    for etf, d in last.items():
        g = df[(df["etf"] == etf) & (df["date"] == d)].sort_values("weight", ascending=False).head(10)
        out[etf] = {r.ticker: D(round(float(r.weight), 6)) for r in g.itertuples()}
    return out, {"date": str(last.max()), "synthetic": bool(df["synthetic"].any())}


def build_sources(prev_date: str, mode: str, store_is_fixture: bool, revenue_asof: str | None,
                  include_revenue: bool) -> dict[str, SourceInfo]:
    ymd = prev_date.replace("-", "")
    man = {e["source"]: e for e in read_manifest(ROOT / "data" / "raw" / ymd)} if not store_is_fixture else {}
    asof = f"{prev_date}T13:30:00+08:00"
    defs = {
        "src:twse_px": ("twse_mi_index", "twse", f"TWSE 每日收盤行情（{prev_date}，含成交股數/金額；歷史價量為本地逐日快照）"),
        "src:tpex_px": ("tpex_daily_quotes", "tpex", f"TPEx 上櫃股票行情（{prev_date}；歷史價量為本地逐日快照）"),
        "src:twse_inst": ("twse_t86", "twse", f"TWSE 三大法人買賣超日報 T86（{prev_date}）"),
        "src:tpex_inst": ("tpex_insti", "tpex", f"TPEx 三大法人買賣明細（{prev_date}）"),
    }
    out = {}
    for key, (src, auth, name) in defs.items():
        e = man.get(src)
        if e:
            url = e["url"]
            fetched = e["fetched_at"] if mode == "live" else None
        else:
            url = f"file:///data/fixtures/{src}/{ymd}"
            name = "[FIXTURE/SYNTHETIC] " + name
            fetched = None
        out[key] = SourceInfo(key, auth, url, name, asof, fetched)
    if include_revenue and revenue_asof:
        url = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue" if not store_is_fixture
               else "file:///data/fixtures/monthly_revenue")
        out["src:revenue"] = SourceInfo("src:revenue", "vendor", url,
                                        ("[FIXTURE/SYNTHETIC] " if store_is_fixture else "")
                                        + "FinMind 月營收（MOPS 月營收彙整；以每月 10 日為保守可得時點）",
                                        revenue_asof)
    return out


@dataclass
class DayResult:
    trade_date: str
    prev_date: str | None
    dplan_path: Path | None
    doc: dict | None
    validation: Report
    result: object
    features: object = None
    scores: pd.DataFrame | None = None
    closes_prev: dict = field(default_factory=dict)
    fallback: bool = False
    notes: list[str] = field(default_factory=list)


def run_day(trade_date: str, store: HistoryStore, prev: Settlement, rb: RuleBook, cfg: dict, *,
            team_id: str, mode: str = "replay", out_dir: Path | None = None, log_dir: Path | None = None,
            method: str | None = None, store_is_fixture: bool = False, calendar: TradingCalendar | None = None,
            run_time: str = "07:00:00") -> DayResult:
    t0 = time.time()
    out_dir = out_dir or ROOT / "out"
    log_dir = log_dir or ROOT / "logs" / "runs" / trade_date.replace("-", "")
    log_dir.mkdir(parents=True, exist_ok=True)
    cal = calendar or TradingCalendar(store.dates("daily_prices") + [trade_date])
    prev_date = cal.prev(trade_date)
    if mode == "live":
        started = datetime.now(TPE).replace(microsecond=0)
        as_of = started.isoformat()
    else:
        as_of = f"{trade_date}T{run_time}+08:00"
        started = datetime.fromisoformat(as_of)
    view = PITView(store, as_of)
    universe = sorted(rb.universe)
    fs = build_features(view, universe, trade_date)
    notes = []
    if fs.last_data_date != prev_date:
        notes.append(f"最新價量日 {fs.last_data_date} ≠ 前一交易日 {prev_date}")
    closes_prev = {t: D(round(float(v), 4)) for t, v in fs.features["close_prev"].dropna().items()}
    sc = score(fs.features, cfg["score_weights"], method or cfg["baseline"]["method"])
    save_features(fs, log_dir / "features")
    save_scores(sc, trade_date, log_dir / "scores")
    etf_h, etf_meta = etf_holdings_from_view(view)
    nav_prev = prev.nav
    if fs.last_data_date != prev_date and prev_date is not None:
        result = FallbackToPreviousPortfolio(f"資料不完整：最新價量日 {fs.last_data_date}，前一交易日 {prev_date}")
    else:
        result = construct(sc, prev.holdings, prev.cash, nav_prev, closes_prev, rb, cfg, fs.market,
                           etf_h or None, etf_meta, method)
    rev = view.monthly_revenue()
    rev_asof = str(rev["available_at"].max()) if len(rev) else None
    sources = build_sources(prev_date or trade_date, mode, store_is_fixture, rev_asof, bool(len(rev)))

    def make(result_obj):
        g, info = build_graph(trade_date, fs, sc, result_obj, prev.holdings, prev.cash, nav_prev, closes_prev,
                              rb, cfg, sources)
        elapsed = max(1, int(time.time() - t0))
        completed = (started + timedelta(seconds=elapsed)) if mode != "live" else datetime.now(TPE).replace(microsecond=0)
        md = {"model_provider": cfg["runtime"]["model_provider"], "model_version": cfg["runtime"]["model_version"],
              "run_started_at": started.isoformat(), "run_completed_at": completed.isoformat(),
              "input_tokens": 0, "output_tokens": 0, "tool_use_count": 0, "code_version": code_version()}
        doc, idmap = export_dplan(g, team_id, md)
        path = write_dplan(doc, out_dir)
        ctx = ValidationContext(prev_holdings=dict(prev.holdings), prev_cash=prev.cash, closes_prev=closes_prev,
                                prev_nav=nav_prev, submission_time=completed.isoformat(), expected_team_id=team_id,
                                filename=str(path), etf_holdings=etf_h or None, etf_data_date=etf_meta.get("date"),
                                etf_synthetic=etf_meta.get("synthetic", False),
                                active_share_target=D(cfg["strategy_buffers"]["active_share_target"]))
        rep = validate_dplan(doc, ctx, rb)
        (log_dir / "evidence_graph.json").write_text(json.dumps(g.to_dict(), ensure_ascii=False, indent=1,
                                                                default=str), encoding="utf-8")
        (log_dir / "id_map.json").write_text(json.dumps(idmap, ensure_ascii=False, indent=1), encoding="utf-8")
        (log_dir / "validation.json").write_text(json.dumps(rep.to_dict(), ensure_ascii=False, indent=1,
                                                            default=str), encoding="utf-8")
        return path, doc, rep

    path, doc, rep = make(result)
    if not rep.ok and not getattr(result, "is_fallback", False):
        notes.append("D-Plan 驗證失敗，改產生 fallback（維持前日組合）："
                     + "; ".join(f"{c.rule_id}:{c.message}" for c in rep.failures[:5]))
        result = FallbackToPreviousPortfolio("D-Plan 驗證失敗：" + "; ".join(c.rule_id for c in rep.failures[:5]))
        path, doc, rep = make(result)
    reports = getattr(result, "reports", []) or []
    (log_dir / "portfolio_reports.json").write_text(json.dumps(
        {"fallback": bool(getattr(result, "is_fallback", False)), "reason": getattr(result, "reason", None),
         "notes": notes + list(getattr(result, "notes", [])), "reports": [r.to_dict() for r in reports],
         "pit_reads": view.reads, "as_of": as_of}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return DayResult(trade_date, prev_date, path, doc, rep, result, fs, sc, closes_prev,
                     bool(getattr(result, "is_fallback", False)), notes + list(getattr(result, "notes", [])))


def day_market(store: HistoryStore, d: str) -> DayMarket:
    """T-day market data for settlement (after close; not a PIT read for decisions)."""
    p = store.load("daily_prices")
    p = p[p["date"] == d]
    close = {r.ticker: D(round(float(r.close), 4)) for r in p.itertuples() if pd.notna(r.close)}
    amount = {r.ticker: D(int(r.amount)) for r in p.itertuples() if pd.notna(r.amount)}
    volume = {r.ticker: D(int(r.volume)) for r in p.itertuples() if pd.notna(r.volume)}
    ca = store.load("corporate_actions")
    ca = ca[ca["ex_date"] == d]
    cash_div = {r.ticker: D(str(r.cash_dividend)) for r in ca.itertuples() if pd.notna(r.cash_dividend) and r.cash_dividend}
    stock_div = {r.ticker: D(str(r.stock_dividend_per_share)) for r in ca.itertuples()
                 if pd.notna(r.stock_dividend_per_share) and r.stock_dividend_per_share}
    return DayMarket(d, close, amount, volume, cash_div, stock_div)


def as_of_weights(holdings: dict[str, int], closes: dict, cash: Decimal) -> dict[str, Decimal]:
    nav = sum((Decimal(s) * D(closes[t]) for t, s in holdings.items()), Decimal(0)) + cash
    return {t: Decimal(s) * D(closes[t]) / nav for t, s in holdings.items()} if nav > 0 else {}
