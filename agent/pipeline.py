"""One trading day: settlement(T-1) -> PIT data -> features -> scores -> portfolio -> compliance
-> orders -> evidence graph -> D-Plan -> validation. Shared by run_daily.py and run_sim.py."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from agent.config import ROOT, D
from agent.data.http import TPE
from agent.data.loaders import SCHEMAS, HistoryStore
from agent.data.manifest import read_manifest
from agent.data.pit import PITView
from agent.dplan.builder import SourceInfo, build_graph
from agent.dplan.exporter import export_dplan, write_dplan
from agent.engine.models import Report, Status
from agent.engine.rules import RuleBook
from agent.engine.validate_dplan import ValidationContext, validate_dplan
from agent.features.feature_engine import FEATURE_VERSION, build_features, save_features
from agent.features.regime import market_regime
from agent.portfolio.constructor import FallbackToPreviousPortfolio, construct
from agent.portfolio import baseline as B
from agent.portfolio.ranking import apply_turnover_scoring, save_scores, score
from agent.sim.calendar import TradingCalendar
from agent.sim.models import DayMarket, Settlement


class DirtyWorkingTreeError(RuntimeError):
    pass


_CODE_VERSION: tuple[str, bool] | None = None


def code_version(refresh: bool = False) -> str:
    """git:<short_sha>; git:<short_sha>-dirty when agent/ or config/ have uncommitted changes.
    Cached per process (the tree must not change during a run)."""
    global _CODE_VERSION
    if _CODE_VERSION is None or refresh:
        try:
            sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                 text=True, timeout=10)
            dirty = subprocess.run(["git", "status", "--porcelain", "--", "agent", "config"], cwd=ROOT,
                                   capture_output=True, text=True, timeout=10)
            if sha.returncode != 0:
                raise RuntimeError(sha.stderr)
            is_dirty = bool(dirty.stdout.strip())
            _CODE_VERSION = ("git:" + sha.stdout.strip() + ("-dirty" if is_dirty else ""), is_dirty)
        except Exception:  # noqa: BLE001
            _CODE_VERSION = ("git:unknown", True)
    return _CODE_VERSION[0]


def working_tree_dirty() -> bool:
    code_version()
    return bool(_CODE_VERSION and _CODE_VERSION[1])


def require_clean_tree() -> None:
    """Competition mode: refuse to run from uncommitted code (code_version must map to a commit)."""
    code_version(refresh=True)
    if working_tree_dirty():
        raise DirtyWorkingTreeError("agent/ or config/ has uncommitted changes; commit before competition run")


def etf_holdings_from_view(view: PITView, prefer_real: bool = True) -> tuple[dict, dict]:
    """Latest visible top-10 per ETF. Real (synthetic=False) rows win over synthetic ones."""
    df = view.etf_holdings()
    if len(df) == 0:
        return {}, {}
    if prefer_real and (~df["synthetic"]).any():
        real_etfs = set(df.loc[~df["synthetic"], "etf"])
        df = df[~(df["etf"].isin(real_etfs) & df["synthetic"])]
    df = df[df["weight"].notna()]
    last = df.groupby("etf")["date"].transform("max")
    df = df[df["date"] == last].sort_values(["etf", "weight"], ascending=[True, False])
    top = df.groupby("etf").head(10)
    out: dict[str, dict] = {}
    for etf, tk, w in zip(top["etf"], top["ticker"], top["weight"]):
        out.setdefault(etf, {})[tk] = D(round(float(w), 6))
    per_etf_date = top.groupby("etf")["date"].max().to_dict()
    return out, {"date": str(top["date"].max()), "synthetic": bool(top["synthetic"].any()),
                 "n_real": int(top.loc[~top["synthetic"], "etf"].nunique()),
                 "n_synthetic": int(top.loc[top["synthetic"], "etf"].nunique()),
                 "per_etf_date": per_etf_date}


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


def add_overnight_sources(out: dict, trade_date: str, market: dict, store_is_fixture: bool) -> dict:
    pre = "[FIXTURE/SYNTHETIC] " if store_is_fixture else ""
    if any(k in market for k in ("overnight_sp500_ret", "overnight_sox_ret", "tsm_adr_ret")):
        out["src:us_overnight"] = SourceInfo(
            "src:us_overnight", "vendor", "https://fred.stlouisfed.org/series/SP500",
            pre + "美股隔夜收盤：S&P500/Nasdaq100 (FRED)、SOX 與 TSM ADR (Yahoo chart, 非官方)",
            market.get("overnight_sp500_ret_available_at") or market.get("overnight_sox_ret_available_at"))
    if "taiex_futures_night_ret" in market:
        out["src:taifex_night"] = SourceInfo(
            "src:taifex_night", "taifex", "https://www.taifex.com.tw/cht/3/futDataDown",
            pre + "TAIFEX 台指期 TX 盤後交易時段（近月合約）",
            f"{market['taiex_futures_night_ret_date']}T05:00:00+08:00")
    if "usd_twd_ret" in market:
        out["src:fx"] = SourceInfo("src:fx", "other", "https://www.cbc.gov.tw/tw/lp-645-1.html",
                                   pre + "中央銀行 新台幣對美元銀行間收盤匯率（前一營業日 16:00）",
                                   market["usd_twd_ret_available_at"])
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
    agent_state: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    llm_summary: dict = field(default_factory=dict)
    event_stats: dict = field(default_factory=dict)
    guard: dict | None = None
    narrative_used_llm: bool = False
    timings: dict = field(default_factory=dict)
    etf_meta: dict = field(default_factory=dict)
    active_share: object = None


_FEATURE_CACHE: dict = {}


FEATURE_TABLES = ("daily_prices", "institutional", "monthly_revenue", "market_overnight")


def _store_fingerprint(store: HistoryStore, tables=None) -> str:
    parts = []
    for p in sorted(store.root.glob("*.parquet")):
        if tables and p.stem not in tables:
            continue
        st = p.stat()
        parts.append(f"{p.name}:{st.st_size}:{int(st.st_mtime)}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def cached_features(store: HistoryStore, as_of: str, trade_date: str, universe: list[str],
                    use_cache: bool = True, disk_cache: bool = True):
    """Features (+ revenue/overnight meta) for (feature-table state, as_of): pure function of PIT data,
    cached in memory and on disk (data/cache/features/<fingerprint>/). ETF holdings are read fresh."""
    import pickle
    fp = _store_fingerprint(store, FEATURE_TABLES)
    key = (str(store.root), fp, as_of, FEATURE_VERSION)
    val = _FEATURE_CACHE.get(key) if use_cache else None
    dpath = ROOT / "data" / "cache" / "features" / f"{FEATURE_VERSION}_{fp}" / (as_of.replace(":", "") + ".pkl")
    if val is None and use_cache and disk_cache and dpath.exists():
        try:
            val = pickle.loads(dpath.read_bytes())
        except Exception:  # noqa: BLE001
            val = None
    if val is None:
        view = PITView(store, as_of)
        fs = build_features(view, universe, trade_date)
        rev = view.monthly_revenue()
        rev_asof = str(rev["available_at"].max()) if len(rev) else None
        val = (fs, rev_asof, bool(len(rev)), list(view.reads))
        if use_cache and disk_cache:
            dpath.parent.mkdir(parents=True, exist_ok=True)
            tmp = dpath.with_suffix(f".tmp{os.getpid()}")
            tmp.write_bytes(pickle.dumps(val))
            os.replace(tmp, dpath)
    if use_cache:
        if len(_FEATURE_CACHE) > 400:
            _FEATURE_CACHE.clear()
        _FEATURE_CACHE[key] = val
    fs, rev_asof, has_rev, reads = val
    etf_h, etf_meta = etf_holdings_from_view(PITView(store, as_of))
    return fs, etf_h, etf_meta, rev_asof, has_rev, reads, None


def update_state_after_settlement(state: dict, prev_holdings: dict, new_holdings: dict, trade_date: str) -> dict:
    """Entry dates / indices follow ACTUAL settled holdings (void trades do not create entries)."""
    st = json.loads(json.dumps(state or {}))
    di = st.get("day_index", 0)
    ent_d, ent_i = st.setdefault("entry_date", {}), st.setdefault("entry_index", {})
    for t in list(ent_d):
        if new_holdings.get(t, 0) <= 0:
            ent_d.pop(t, None)
            ent_i.pop(t, None)
    for t, s in new_holdings.items():
        if s > 0 and prev_holdings.get(t, 0) <= 0:
            ent_d[t] = trade_date
            ent_i[t] = di
    return st


def run_day(trade_date: str, store: HistoryStore, prev: Settlement, rb: RuleBook, cfg: dict, *,
            team_id: str, mode: str = "replay", out_dir: Path | None = None, log_dir: Path | None = None,
            method: str | None = None, store_is_fixture: bool = False, calendar: TradingCalendar | None = None,
            run_time: str = "07:00:00", light: bool = False, use_cache: bool = True,
            data_faults: set[str] | None = None, llm: dict | None = None) -> DayResult:
    """light=True: research mode (no per-day feature/score/graph logs; D-Plan + validation still produced).
    data_faults: inputs to drop (fault injection) e.g. {'institutional','revenue','etf','overnight'}.
    llm: None (pure quant, templates) or {"cfg": llm.yaml dict, "provider": optional provider instance,
         "log_root": optional Path}. LLM output can only touch TEXT, plus (if llm_signal.enabled) a bounded
         score adjustment applied by deterministic code; any LLM failure falls back to templates/no-adjustment."""
    t0 = time.perf_counter()
    tm: dict[str, float] = {}
    out_dir = out_dir or ROOT / "out"
    log_dir = log_dir or ROOT / "logs" / "runs" / trade_date.replace("-", "")
    if not light:
        log_dir.mkdir(parents=True, exist_ok=True)
    cal = calendar or TradingCalendar(store.dates("daily_prices") + [trade_date])
    prev_date = cal.prev(trade_date)
    if mode == "live":
        started = datetime.now(TPE).replace(microsecond=0)
        as_of = started.isoformat()
    else:
        as_of = f"{trade_date}T{run_time}+08:00"
        started = datetime.fromisoformat(as_of)
    universe = sorted(rb.universe)
    faults = data_faults or set()
    fs, etf_h, etf_meta, rev_asof, has_rev, reads, ovn = cached_features(store, as_of, trade_date, universe,
                                                                        use_cache)
    tm["data_features"] = time.perf_counter() - t0
    if faults:
        fs = _inject_faults(fs, faults)
        if "etf" in faults:
            etf_h, etf_meta = {}, {}
        if "revenue" in faults:
            has_rev = False
        if "overnight" in faults:
            ovn = None
    notes = []
    if fs.last_data_date != prev_date:
        notes.append(f"最新價量日 {fs.last_data_date} ≠ 前一交易日 {prev_date}")
    closes_prev = {t: D(round(float(v), 4)) for t, v in fs.features["close_prev"].dropna().items()}

    t1 = time.perf_counter()
    tp = B.turnover_params(cfg)
    state = json.loads(json.dumps(prev.agent_state or {}))
    di = state.get("day_index", -1) + 1
    held = {t for t, s in prev.holdings.items() if s > 0}
    sc = score(fs.features, cfg["score_weights"], method or cfg["baseline"]["method"])
    # ---- Phase 5: LLM client (per day budget), event extraction, bounded fusion
    client = None
    events, ev_stats, audit = [], {}, None
    if llm:
        from agent.llm.client import LLMClient
        from agent.llm.logging import LLMCallLogger
        lcfg = llm["cfg"]
        client = LLMClient(lcfg, provider=llm.get("provider"),
                           logger=LLMCallLogger(llm.get("log_root"), trade_date, bool(lcfg.get("log_calls", True))))
        if lcfg.get("events", {}).get("enabled") and client.enabled and "events" not in faults:
            from agent.research.event_extractor import EventExtractor, revenue_facts, visible_documents
            te = time.perf_counter()
            docs = visible_documents(PITView(store, as_of), trade_date, set(rb.universe),
                                     int(lcfg["events"].get("lookback_days", 5)),
                                     int(lcfg["events"].get("max_documents_per_day", 200)))
            ex = EventExtractor(client, rb.universe, ROOT / "data" / "cache" / "events")
            events = ex.extract(docs, revenue_facts(fs.features, sorted({d.ticker for d in docs})))
            ev_stats = dict(ex.stats.__dict__, hallucinations=ex.stats.hallucinations)
            tm["events"] = time.perf_counter() - te
        sig = lcfg.get("llm_signal", {})
        if sig.get("enabled") and events:
            from agent.portfolio.signal_fusion import fuse
            from agent.research.event_extractor import event_scores
            es = event_scores(events, trade_date, float(sig.get("min_confidence", 0.7)), sig.get("decay", "linear"))
            sc, audit = fuse(sc, es, float(sig.get("max_percentile_adjustment", 5)))
    sc, new_ema = apply_turnover_scoring(sc, state.get("score_ema", {}), held, tp)
    holding_days = {t: di - int(state.get("entry_index", {}).get(t, di - 10**6)) for t in held}
    last_rb = state.get("last_rebalance_index")
    is_rb = (last_rb is None) or (di - int(last_rb) >= int(tp["rebalance_every"])) or not held
    regime_tuple = market_regime(fs, ovn, cfg) if cfg.get("regime", {}).get("use_v0", False) else None
    guard = None
    if (cfg.get("crash_guard") or {}).get("enabled"):
        from agent.risk import crash_guard as CG
        guard = CG.step(state.get("guard"), fs.market, CG.portfolio_drawdown(prev.nav_history, prev.initial_nav), cfg)
        vol = fs.features["volatility_20d"].dropna()
        guard["high_vol"] = sorted(vol[vol >= vol.quantile(guard["high_vol_quantile"])].index) if len(vol) else []
        if guard["state"] != (state.get("guard") or {}).get("state", "NORMAL"):
            is_rb = True                      # state change -> act today (scaling is capped per day)
    tm["ranking"] = time.perf_counter() - t1
    if not light:
        save_features(fs, log_dir / "features")
        save_scores(sc, trade_date, log_dir / "scores")
    nav_prev = prev.nav

    t2 = time.perf_counter()
    if fs.last_data_date != prev_date and prev_date is not None:
        result = FallbackToPreviousPortfolio(f"資料不完整：最新價量日 {fs.last_data_date}，前一交易日 {prev_date}")
    else:
        result = construct(sc, prev.holdings, prev.cash, nav_prev, closes_prev, rb, cfg, fs.market,
                           etf_h or None, etf_meta, method, holding_days, is_rb,
                           regime_tuple[:4] if regime_tuple else None, guard)
    tm["portfolio"] = time.perf_counter() - t2
    sources = build_sources(prev_date or trade_date, mode, store_is_fixture, rev_asof, has_rev)
    sources = add_overnight_sources(sources, trade_date, fs.market, store_is_fixture)

    narrator = writer = None
    if client is not None and llm["cfg"].get("narrative", {}).get("mode") == "llm" and client.enabled:
        from agent.research.market_narrator import LLMMarketNarrator
        from agent.research.thesis_writer import LLMThesisWriter
        narrator = LLMMarketNarrator(client)
        writer = LLMThesisWriter(client, int(llm["cfg"]["narrative"].get("max_thesis_items", 35)))

    def make(result_obj):
        ta = time.perf_counter()
        g, info = build_graph(trade_date, fs, sc, result_obj, prev.holdings, prev.cash, nav_prev, closes_prev,
                              rb, cfg, sources, narrator, writer, events, audit)
        elapsed = max(1, int(time.perf_counter() - t0))
        completed = (started + timedelta(seconds=elapsed)) if mode != "live" else datetime.now(TPE).replace(microsecond=0)
        used = client is not None and client.enabled and (narrator is not None or bool(events))
        md = {"model_provider": _provider_enum(client.provider_name) if used else cfg["runtime"]["model_provider"],
              "model_version": (client.model_version or "unknown")[:60] if used else cfg["runtime"]["model_version"],
              "run_started_at": started.isoformat(), "run_completed_at": completed.isoformat(),
              "input_tokens": int(client.logger.summary()["input_tokens"]) if used else 0,
              "output_tokens": int(client.logger.summary()["output_tokens"]) if used else 0,
              "tool_use_count": int(client.logger.summary()["calls"]) if used else 0, "code_version": code_version()}
        doc, idmap = export_dplan(g, team_id, md)
        path = write_dplan(doc, out_dir)
        tb = time.perf_counter()
        ctx = ValidationContext(prev_holdings=dict(prev.holdings), prev_cash=prev.cash, closes_prev=closes_prev,
                                prev_nav=nav_prev, submission_time=completed.isoformat(), expected_team_id=team_id,
                                filename=str(path), etf_holdings=etf_h or None, etf_data_date=etf_meta.get("date"),
                                etf_synthetic=etf_meta.get("synthetic", False),
                                active_share_target=D(cfg["strategy_buffers"]["active_share_target"]))
        rep = validate_dplan(doc, ctx, rb)
        tm["dplan"] = tm.get("dplan", 0) + (tb - ta)
        tm["validation"] = tm.get("validation", 0) + (time.perf_counter() - tb)
        if not light:
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
    traded = bool(doc and doc.get("orders"))
    state.update({"day_index": di, "score_ema": new_ema,
                  "last_rebalance_index": di if (traded or last_rb is None) else last_rb,
                  "regime": None if regime_tuple is None else {"regime": regime_tuple[0], "score": regime_tuple[4]},
                  "guard": None if guard is None else {k: guard[k] for k in ("state", "raw_state", "points", "calm_days")}})
    tm["total"] = time.perf_counter() - t0
    reports = getattr(result, "reports", []) or []
    if not light:
        (log_dir / "portfolio_reports.json").write_text(json.dumps(
            {"fallback": bool(getattr(result, "is_fallback", False)), "reason": getattr(result, "reason", None),
             "notes": notes + list(getattr(result, "notes", [])), "reports": [r.to_dict() for r in reports],
             "pit_reads": reads, "as_of": as_of, "timings_sec": tm, "code_version": code_version()},
            ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return DayResult(trade_date, prev_date, path, doc, rep, result, fs, sc, closes_prev,
                     bool(getattr(result, "is_fallback", False)), notes + list(getattr(result, "notes", [])),
                     state, tm, etf_meta, getattr(result, "active_share", None), events,
                     client.logger.summary() if client is not None else {}, ev_stats, guard,
                     bool(narrator is not None and getattr(narrator, "used_llm", False)))


def _provider_enum(name: str) -> str:
    """D-Plan agent_metadata.model_provider enum (schema): map our provider names."""
    return {"google": "google", "gemini": "google", "openai": "openai", "anthropic": "anthropic"}.get(name, "other")


def _inject_faults(fs, faults: set[str]):
    """Copy of the FeatureSet with selected inputs removed (fault-injection tests)."""
    import copy
    import numpy as np
    f2 = copy.copy(fs)
    df = fs.features.copy()
    if "institutional" in faults:
        for c in ("institutional_flow_5d", "institutional_flow_20d", "inst_net_5d_shares", "inst_net_20d_shares"):
            df[c] = np.nan
    if "revenue" in faults:
        for c in ("revenue_yoy", "revenue_mom"):
            df[c] = np.nan
        df["revenue_ym"] = None
    if "overnight" in faults:
        for c in [c for c in df.columns if c.startswith("overnight_") or c in ("tsm_adr_ret", "taiex_futures_night_ret", "usd_twd_ret")]:
            df[c] = np.nan
    f2.features = df
    return f2


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
