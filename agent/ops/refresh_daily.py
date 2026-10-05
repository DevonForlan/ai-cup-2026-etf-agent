"""Daily data refresh orchestration for trade date T (data of T-1 and the overnight session).

Each source -> SourceStatus(source, criticality, requested_date, latest_available_date, status, records,
fetched_at, content_as_of, stale, error, duration). Failures never raise: OPTIONAL failures only warn,
IMPORTANT failures degrade, CRITICAL failures block (decided by preflight / competition_day).
Writes logs/ops/YYYYMMDD/data_health.json + .md.

  python agent\\ops\\refresh_daily.py --date 2026-10-06 [--only twse_prices,tpex_prices] [--skip us_market]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT, load_data_sources, load_universe  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.ops.common import (TPE, Clock, load_ops_config, ops_logger, ops_path, sha256_bytes,  # noqa: E402
                              sha256_file, write_json, ymd)


@dataclass
class SourceStatus:
    source: str
    criticality: str
    requested_date: str
    latest_available_date: str | None = None
    status: str = "PENDING"          # OK | STALE | FAILED | SKIPPED
    records: int = 0
    fetched_at: str | None = None
    content_as_of: str | None = None
    stale: bool = False
    error: str | None = None
    duration: float = 0.0
    detail: dict = field(default_factory=dict)
    fallback: str | None = None      # "store" when the result comes from a store probe after a failed fetch


def prev_weekdays(d: str, n: int = 6) -> list[str]:
    x = date.fromisoformat(d)
    out = []
    while len(out) < n:
        x -= timedelta(days=1)
        if x.weekday() < 5:
            out.append(x.isoformat())
    return out


def stale_trading_days(latest: str | None, requested: str) -> int | None:
    if not latest:
        return None
    return int(pd.bdate_range(latest, requested).size) - 1


# ----------------------------------------------------------------------------- default fetchers
# Each fetcher(ctx) -> dict(records, latest_available_date, content_as_of, detail). Raise on failure.
def _session():
    from agent.data.http import make_session
    return make_session(load_data_sources()["http"]["relax_x509_strict"])


def _fetch_quotes(market: str):
    def f(ctx):
        from agent.data.fetchers import tpex, twse
        cfg = load_data_sources()
        av = cfg["availability"]
        uni = {t for t, v in load_universe().items() if v["market"] == ("TWSE" if market == "twse" else "TPEx")}
        mod = twse if market == "twse" else tpex
        s = ctx.setdefault("session", _session())
        have = ctx["store"].load("daily_prices")
        for d in prev_weekdays(ctx["trade_date"], 6):          # newest weekday with data (holidays skipped)
            n_have = int(have[(have["date"] == d) & have["ticker"].isin(uni)]["ticker"].nunique()) if len(have) else 0
            if n_have >= 0.9 * len(uni) and not ctx.get("force"):   # already stored -> no network call needed
                return {"records": 0, "latest_available_date": d, "content_as_of": f"{d}T13:30:00+08:00",
                        "detail": {"cached": True}}
            rows, _ = mod.fetch_daily_quotes(s, cfg, d, uni, av["daily_prices"])
            if rows:
                n = ctx["store"].upsert("daily_prices", [dict(r, available_at=f"{d}T{av['daily_prices']}:00+08:00")
                                                         for r in rows])
                return {"records": n, "latest_available_date": d, "content_as_of": f"{d}T13:30:00+08:00"}
        raise RuntimeError("no price data in the last 6 weekdays")
    return f


def _fetch_insti(market: str):
    def f(ctx):
        from agent.data.fetchers import tpex, twse
        cfg = load_data_sources()
        av = cfg["availability"]
        uni = {t for t, v in load_universe().items() if v["market"] == ("TWSE" if market == "twse" else "TPEx")}
        mod = twse if market == "twse" else tpex
        s = ctx.setdefault("session", _session())
        for d in prev_weekdays(ctx["trade_date"], 6):
            rows, _ = mod.fetch_institutional(s, cfg, d, uni, av["institutional"])
            if rows:
                n = ctx["store"].upsert("institutional", [dict(r, available_at=f"{d}T{av['institutional']}:00+08:00")
                                                          for r in rows])
                return {"records": n, "latest_available_date": d, "content_as_of": f"{d}T13:30:00+08:00"}
        raise RuntimeError("no institutional data in the last 6 weekdays")
    return f


def _etf_ok(r) -> bool:
    return r is not None and r.status in ("ok", "stale") and bool(r.rows)


def etf_fetch_with_policy(session, etf: str, fetch_one, run_date: str, prev_dates: int = 3):
    """Round 06 retry policy: latest -> retry latest once -> up to `prev_dates` previous published dates
    (issuers with history) -> None (caller keeps the STORED prior snapshot = STALE_FALLBACK).
    Never fabricates today's data. Returns (Result | None, status, attempts)."""
    attempts = []
    for label in ("latest", "retry_latest"):
        r = fetch_one(session, etf, None, save=True)
        attempts.append({"try": label, "status": r.status, "reason": r.reason})
        if _etf_ok(r):
            return r, ("OK" if label == "latest" else "RETRY_OK"), attempts
    for d in prev_weekdays(run_date, prev_dates):
        r = fetch_one(session, etf, d, save=True)
        attempts.append({"try": f"date {d}", "status": r.status, "reason": r.reason})
        if _etf_ok(r):
            return r, "PREVIOUS_DATE", attempts
        if r.status == "no_history":                       # issuer shows latest only
            break
    return None, "STALE_FALLBACK", attempts


def _fetch_etf(ctx):
    """Holdings for all 30 official active ETFs + append-only daily snapshot (never overwrites).
    Per-ETF retry / previous-date / stored-snapshot fallback; optional small parallelism (config
    etf_fetch.max_workers, default 1 = sequential; issuers' rate limits are respected per request)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from agent.data.fetchers import etf_holdings as E
    from agent.config import load_active_etfs
    ecfg = ctx["ops_cfg"].get("etf_fetch") or {}
    workers = max(1, min(int(ctx.get("etf_max_workers") or ecfg.get("max_workers", 1)), 5))
    fetch_one = ctx.get("etf_fetch_one") or E.fetch_one
    make_session = ctx.get("etf_session") or E._session
    local = threading.local()

    def one(etf):
        if not hasattr(local, "s"):
            local.s = make_session()                         # one HTTP session per worker thread
        return etf, etf_fetch_with_policy(local.s, etf, fetch_one, ctx["run_date"], int(ecfg.get("previous_dates", 3)))

    etfs = [x["etf"] for x in load_active_etfs()]
    if workers == 1:
        results = [one(e) for e in etfs]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(one, etfs))
    snap_dir = ops_path(ctx["ops_cfg"], "etf_snapshots_dir") / ymd(ctx["run_date"])
    snap_dir.mkdir(parents=True, exist_ok=True)
    stamp = ctx["wall"].now().strftime("%H%M%S")
    stored = ctx["store"].load("etf_holdings")
    stored_latest = stored.groupby("etf")["date"].max().to_dict() if len(stored) else {}
    manifest, rows_all, latest, failed, by_status = [], [], [], [], {}
    for e, (r, status, attempts) in results:
        by_status[status] = by_status.get(status, 0) + 1
        if r is None:
            prior = stored_latest.get(e)
            failed.append({"etf": e, "status": status, "prior_holdings_date": prior, "attempts": attempts})
            manifest.append({"etf": e, "status": status, "file": None, "holdings_date": prior,
                             "note": "stored prior snapshot kept; NOT today's data"})
            if prior:
                latest.append(prior)
            continue
        rows_all += r.rows
        latest.append(r.asof)
        body = json.dumps(r.rows, ensure_ascii=False, default=str).encode("utf-8")
        p = snap_dir / f"{e}_{stamp}.json"
        if p.exists():
            raise RuntimeError(f"snapshot exists, refusing to overwrite {p}")
        p.write_bytes(body)
        manifest.append({"etf": e, "status": status, "file": p.name, "sha256": sha256_bytes(body),
                         "holdings_date": r.asof, "rows": len(r.rows), "source_url": r.rows[0].get("source_url"),
                         "published_at": r.rows[0].get("published_at"), "fetched_at": r.rows[0].get("fetched_at"),
                         "attempts": len(attempts)})
    mf = snap_dir / f"manifest_{stamp}.json"
    if mf.exists():
        raise RuntimeError(f"snapshot manifest exists, refusing to overwrite {mf}")
    write_json(mf, {"snapshot_time": ctx["wall"].now().isoformat(), "workers": workers, "by_status": by_status,
                    "files": manifest, "failed": failed})
    rows_all = [x for x in rows_all if not x.get("synthetic")]
    n = ctx["store"].upsert("etf_holdings", rows_all) if rows_all else 0
    fresh = sum(v for k, v in by_status.items() if k != "STALE_FALLBACK")
    if not fresh:
        raise RuntimeError(f"no ETF holdings fetched ({len(failed)} on stored fallback)")
    try:
        mrel = str(mf.relative_to(ROOT))
    except ValueError:
        mrel = str(mf)
    return {"records": n, "latest_available_date": min(latest), "content_as_of": max(latest),
            "detail": {"etfs_fresh": fresh, "by_status": by_status, "etfs_fallback": failed,
                       "workers": workers, "snapshot_manifest": mrel}}


def _fetch_corporate_actions(ctx):
    from agent.data.fetchers.corporate_actions import fetch_corporate_actions
    uni = load_universe()
    t = ctx["trade_date"]
    start = (date.fromisoformat(t) - timedelta(days=14)).isoformat()
    ev, stats = fetch_corporate_actions(start, t, {k for k, v in uni.items() if v["market"] == "TWSE"},
                                        {k for k, v in uni.items() if v["market"] == "TPEx"})
    n = ctx["store"].upsert("corporate_actions", ev) if ev else 0
    return {"records": n, "latest_available_date": prev_weekdays(t, 1)[0], "content_as_of": t,
            "detail": {k: v for k, v in stats.items() if k != "failed"} | {"failed": len(stats.get("failed", []))}}


def _fetch_material(ctx):
    from agent.data.fetchers import material_info as M
    uni = set(load_universe())
    t = date.fromisoformat(ctx["trade_date"])
    days = [t - timedelta(days=i) for i in (3, 2, 1, 0)]        # T-3..T (listing of D holds D-1 evening too)
    done = M.load_done()
    for d in days[-2:]:
        done.pop(d.isoformat(), None)                            # always refresh the last two days
    stats = M.run_range(days, ctx["store"], uni, _session(), done)
    return {"records": stats["universe"] if "universe" in stats else stats.get("fetched", 0),
            "latest_available_date": days[-1].isoformat(), "content_as_of": ctx["wall"].now().isoformat(),
            "detail": stats}


def append_first_seen(obs: list[dict], ledger: Path, fetched_at: str, source: str) -> int:
    """Append-only ledger of the FIRST time each (ticker, revenue month) was observed. Never rewrites."""
    cols = ["ticker", "revenue_month", "first_seen_at", "source", "value"]
    cur = pd.read_parquet(ledger) if ledger.exists() else pd.DataFrame(columns=cols)
    seen = set(zip(cur["ticker"].astype(str), cur["revenue_month"].astype(str)))
    new = []
    for o in obs:
        k = (str(o["ticker"]), f"{int(o['year']):04d}-{int(o['month']):02d}")
        if k not in seen:
            seen.add(k)
            new.append({"ticker": k[0], "revenue_month": k[1], "first_seen_at": fetched_at, "source": source,
                        "value": float(o["revenue"]) if o.get("revenue") is not None else None})
    if new:
        out = pd.concat([cur, pd.DataFrame(new)], ignore_index=True) if len(cur) else pd.DataFrame(new)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        tmp = ledger.with_suffix(".tmp")
        out.to_parquet(tmp, index=False)
        tmp.replace(ledger)
    return len(new)


def first_seen_available(ledger: Path, as_of: str) -> pd.DataFrame:
    """Replay helper: only rows with first_seen_at <= as_of are usable."""
    if not ledger.exists():
        return pd.DataFrame(columns=["ticker", "revenue_month", "first_seen_at", "source", "value"])
    df = pd.read_parquet(ledger)
    return df[df["first_seen_at"] <= as_of]


def _fetch_revenue_first_seen(ctx):
    from agent.data.fetchers.revenue_dates import observe_mops
    t = date.fromisoformat(ctx["trade_date"])
    first = t.replace(day=1) - timedelta(days=1)                 # previous month (the one being published)
    obs = observe_mops(first.year, first.month, session=_session())
    uni = set(load_universe())
    obs = [o for o in obs if o["ticker"] in uni]
    now = ctx["wall"].now().isoformat()      # real observation time (never the simulated clock)
    n = append_first_seen(obs, ops_path(ctx["ops_cfg"], "first_seen_ledger"), now, "mops_t21sc03")
    # make newly seen months usable from their first-seen time (never later than the legal deadline)
    if n:
        from agent.data.fetchers.revenue_dates import placeholder_available_at
        rows = []
        for o in obs:
            ph = placeholder_available_at(int(o["year"]), int(o["month"]))
            rows.append({"ticker": o["ticker"], "year": int(o["year"]), "month": int(o["month"]),
                         "revenue": o["revenue"], "published_date": now[:10], "available_at": min(ph, now)})
        cur = ctx["store"].load("monthly_revenue")
        have = set(zip(cur["ticker"], cur["year"].astype(int), cur["month"].astype(int)))
        rows = [r for r in rows if (r["ticker"], r["year"], r["month"]) not in have]
        if rows:
            ctx["store"].upsert("monthly_revenue", rows)
    return {"records": n, "latest_available_date": f"{first:%Y-%m}", "content_as_of": now,
            "detail": {"observed": len(obs), "new_first_seen": n}}


def _fetch_taifex(ctx):
    from agent.data.fetchers.taifex import fetch_night_session
    t = ctx["trade_date"]
    rows = fetch_night_session(_session(), (date.fromisoformat(t) - timedelta(days=7)).isoformat(), t, log=None)
    if not rows:
        raise RuntimeError("no night-session rows")
    n = ctx["store"].upsert("market_overnight", rows)
    return {"records": n, "latest_available_date": max(r["date"] for r in rows),
            "content_as_of": f"{max(r['date'] for r in rows)}T05:00:00+08:00"}


def _fetch_us(ctx):
    from agent.data.overnight import default_provider
    t = ctx["trade_date"]
    prov = default_provider(save=True, log=None)
    rows = prov.get(["SPX", "NDX", "IXIC", "SOX", "TSM", "USDTWD"], (date.fromisoformat(t) - timedelta(days=10)).isoformat(), t)
    if not rows:
        raise RuntimeError(f"no US/FX rows: {prov.status}")
    n = ctx["store"].upsert("market_overnight", rows)
    by = {}
    for r in rows:
        by[r["symbol"]] = max(by.get(r["symbol"], ""), r["date"])
    return {"records": n, "latest_available_date": min(by.values()), "content_as_of": max(by.values()),
            "detail": {"per_symbol_latest": by, "provider_status": prov.status}}


DEFAULT_FETCHERS: dict[str, Callable] = {
    "twse_prices": _fetch_quotes("twse"), "tpex_prices": _fetch_quotes("tpex"),
    "twse_institutional": _fetch_insti("twse"), "tpex_institutional": _fetch_insti("tpex"),
    "etf_holdings": _fetch_etf, "corporate_actions": _fetch_corporate_actions,
    "mops_revenue_first_seen": _fetch_revenue_first_seen, "mops_material_info": _fetch_material,
    "taifex_night": _fetch_taifex, "us_market": _fetch_us,
}
# ----------------------------------------------------------------------------- store probes
# When a fetch fails (network down, site error) the run may still be fine if the store ALREADY holds the
# required rows (fetched earlier). A probe returns the newest usable date in the store (<= the date a
# decision for trade_date may use) -> status CACHED. It never invents or forward-fills data: a missing T-1
# critical price stays FAILED/STALE -> BLOCK.
def _probe_prices(market: str):
    def f(store, trade_date):
        uni = {t for t, v in load_universe().items() if v["market"] == ("TWSE" if market == "twse" else "TPEx")}
        p = store.load("daily_prices")
        p = p[(p["date"] < trade_date) & p["ticker"].isin(uni)]
        if not len(p):
            return None
        cnt = p.groupby("date")["ticker"].nunique()
        ok = cnt[cnt >= 0.9 * len(uni)]
        return max(ok.index) if len(ok) else None
    return f


def _probe_insti(market: str):
    def f(store, trade_date):
        uni = {t for t, v in load_universe().items() if v["market"] == ("TWSE" if market == "twse" else "TPEx")}
        p = store.load("institutional")
        p = p[(p["date"] < trade_date) & p["ticker"].isin(uni)]
        return max(p["date"]) if len(p) else None
    return f


def _probe_etf(store, trade_date):
    e = store.load("etf_holdings")
    e = e[e["date"] < trade_date]
    return min(e.groupby("etf")["date"].max()) if len(e) else None


def _probe_overnight(symbols):
    def f(store, trade_date):
        m = store.load("market_overnight")
        m = m[(m["date"] <= trade_date) & m["symbol"].isin(symbols)]
        if not len(m) or set(m["symbol"]) < set(symbols):
            return None
        return min(m.groupby("symbol")["date"].max())
    return f


STORE_PROBES: dict[str, Callable] = {
    "twse_prices": _probe_prices("twse"), "tpex_prices": _probe_prices("tpex"),
    "twse_institutional": _probe_insti("twse"), "tpex_institutional": _probe_insti("tpex"),
    "etf_holdings": _probe_etf, "taifex_night": _probe_overnight(["TXF_NIGHT"]),
    "us_market": _probe_overnight(["SPX", "SOX", "TSM", "USDTWD"]),
}


def replay_fetchers() -> dict[str, Callable]:
    """Historical rehearsal: each source 'refreshes' by reading what the store held for trade_date (no network).
    Reports the newest usable date and row counts so data_health is produced exactly like a live day; a
    source without usable rows fails (and is then judged by the same policy)."""
    def from_probe(name):
        def f(ctx):
            latest = STORE_PROBES[name](ctx["store"], ctx["trade_date"])
            if not latest:
                raise RuntimeError(f"{name}: no rows in store before {ctx['trade_date']}")
            return {"records": 0, "latest_available_date": latest, "content_as_of": latest,
                    "detail": {"mode": "replay-store"}}
        return f

    def corp(ctx):
        ca = ctx["store"].load("corporate_actions")
        n = int((ca["available_at"].astype(str) < ctx["trade_date"]).sum()) if len(ca) else 0
        return {"records": n, "latest_available_date": prev_weekdays(ctx["trade_date"], 1)[0],
                "detail": {"mode": "replay-store", "events_visible": n}}

    def revenue(ctx):
        r = ctx["store"].load("monthly_revenue")
        r = r[r["available_at"].astype(str) < ctx["trade_date"]] if len(r) else r
        if not len(r):
            raise RuntimeError("no revenue visible")
        ym = max(f"{int(y):04d}-{int(m):02d}" for y, m in zip(r["year"], r["month"]))
        return {"records": len(r), "latest_available_date": ym, "detail": {"mode": "replay-store"}}

    def material(ctx):
        m = ctx["store"].load("material_info")
        m = m[m["published_at"].astype(str) < ctx["trade_date"]] if len(m) else m
        if not len(m):
            raise RuntimeError("no material info visible")
        return {"records": len(m), "latest_available_date": str(max(m["published_at"]))[:10],
                "detail": {"mode": "replay-store"}}
    out = {k: from_probe(k) for k in STORE_PROBES}
    out.update(corporate_actions=corp, mops_revenue_first_seen=revenue, mops_material_info=material)
    return out


def offline_fetchers(reason: str = "network unavailable (offline mode)") -> dict[str, Callable]:
    """Every source 'fails' without touching the network -> each result comes only from a store probe.
    Used for replay rehearsals and the network-down drill."""
    def fail(ctx):
        raise ConnectionError(reason)
    return {k: fail for k in DEFAULT_FETCHERS}


HEAVY = {"etf_holdings", "corporate_actions", "mops_material_info", "mops_revenue_first_seen"}


def refresh(trade_date: str, *, store: HistoryStore | None = None, fetchers: dict | None = None,
            ops_cfg: dict | None = None, clock: Clock | None = None, only: set | None = None,
            skip: set | None = None, allow_noncritical: bool = True, run_date: str | None = None,
            wall_clock: Clock | None = None) -> dict:
    """`clock` may be simulated (deadline tests / dry runs); every OBSERVATION timestamp (fetched_at, ETF
    snapshot folder, MOPS first_seen_at, available_at of newly seen revenue) uses `wall_clock` = real time,
    otherwise a simulated past clock would make data look available earlier than it was (PIT leak)."""
    ops_cfg = ops_cfg or load_ops_config()
    clock = clock or Clock()
    store = store or HistoryStore()
    fetchers = fetchers or DEFAULT_FETCHERS
    lg = ops_logger(trade_date, "refresh", ops_cfg)
    wall = wall_clock or Clock()
    ctx = {"trade_date": trade_date, "store": store, "ops_cfg": ops_cfg, "clock": clock, "wall": wall,
           "run_date": run_date or wall.now().strftime("%Y-%m-%d")}
    out: list[SourceStatus] = []
    for name, meta in ops_cfg["data_sources"].items():
        st = SourceStatus(name, meta["criticality"], trade_date)
        if (only and name not in only) or (skip and name in skip) or name not in fetchers:
            st.status = "SKIPPED"
            st.error = "not requested" if name in fetchers else "no fetcher"
            out.append(st)
            continue
        if not allow_noncritical and meta["criticality"] != "CRITICAL" and name in HEAVY:
            st.status = "SKIPPED"
            st.error = "deadline guard: non-critical refresh skipped"
            out.append(st)
            continue
        t0 = time.perf_counter()
        try:
            r = fetchers[name](ctx)
            st.records = int(r.get("records", 0))
            st.latest_available_date = r.get("latest_available_date")
            st.content_as_of = r.get("content_as_of")
            st.detail = r.get("detail", {})
            st.fetched_at = wall.now().isoformat()
            lag = stale_trading_days(st.latest_available_date, prev_weekdays(trade_date, 1)[0]) \
                if st.latest_available_date and len(st.latest_available_date) == 10 else None
            st.stale = lag is not None and lag > int(meta.get("max_stale_trading_days", 0))
            st.status = "STALE" if st.stale else "OK"
        except Exception as e:  # noqa: BLE001
            st.status = "FAILED"
            st.error = f"{type(e).__name__}: {e}"[:400]
            probe = (ctx.get("probes") or STORE_PROBES).get(name)
            latest = probe(store, trade_date) if probe else None
            if latest:
                lag = stale_trading_days(latest, prev_weekdays(trade_date, 1)[0]) if len(latest) == 10 else None
                st.latest_available_date = latest
                st.fallback = "store"
                if lag is not None and lag <= int(meta.get("max_stale_trading_days", 0)):
                    st.status = "CACHED"                # required rows already in the store
                else:
                    st.status, st.stale = "STALE", True
        st.duration = round(time.perf_counter() - t0, 2)
        lg.info(f"{name} {st.status} records={st.records} latest={st.latest_available_date} {st.error or ''}")
        out.append(st)
    report = summarize(trade_date, out, store)
    d = ops_path(ops_cfg, "ops_logs_dir") / ymd(trade_date)
    write_json(d / "data_health.json", report)
    (d / "data_health.md").write_text(to_markdown(report), encoding="utf-8")
    return report


def summarize(trade_date: str, sts: list[SourceStatus], store: HistoryStore) -> dict:
    lvl = "PASS"
    for s in sts:
        if s.status in ("FAILED", "STALE"):
            if s.criticality == "CRITICAL":
                lvl = "BLOCK"
            elif lvl != "BLOCK":
                lvl = "WARN"
        elif s.status == "CACHED" and lvl == "PASS":
            lvl = "WARN"                     # fetch failed but store already holds the rows -> DEGRADED run
    hashes = {p.name: sha256_file(p) for p in sorted(store.root.glob("*.parquet"))}
    return {"trade_date": trade_date, "level": lvl, "sources": [asdict(s) for s in sts],
            "store_manifest_hash": __import__("agent.ops.common", fromlist=["sha256_json"]).sha256_json(hashes),
            "store_files": hashes}


def to_markdown(r: dict) -> str:
    lines = [f"# Data health — trade date {r['trade_date']}: **{r['level']}**", "",
             "| source | criticality | status | latest | records | stale | duration s | error |",
             "|---|---|---|---|---|---|---|---|"]
    for s in r["sources"]:
        lines.append(f"| {s['source']} | {s['criticality']} | {s['status']} | {s['latest_available_date'] or '-'} | "
                     f"{s['records']} | {s['stale']} | {s['duration']} | {(s['error'] or '')[:80]} |")
    lines += ["", f"store manifest hash: `{r['store_manifest_hash']}`"]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="trade date T (refreshes T-1 data + overnight)")
    ap.add_argument("--only", default=None)
    ap.add_argument("--skip", default=None)
    a = ap.parse_args(argv)
    r = refresh(a.date, only=set(a.only.split(",")) if a.only else None,
                skip=set(a.skip.split(",")) if a.skip else None)
    print(to_markdown(r))
    return 0 if r["level"] != "BLOCK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
