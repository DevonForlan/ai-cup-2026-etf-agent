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


def _fetch_etf(ctx):
    """Latest holdings for all 30 official active ETFs + append-only daily snapshot (never overwrites)."""
    from agent.data.fetchers import etf_holdings as E
    from agent.config import load_active_etfs
    s = E._session()
    snap_dir = ops_path(ctx["ops_cfg"], "etf_snapshots_dir") / ymd(ctx["run_date"])
    snap_dir.mkdir(parents=True, exist_ok=True)
    stamp = ctx["clock"].now().strftime("%H%M%S")
    manifest, rows_all, latest, failed = [], [], [], []
    for e in [x["etf"] for x in load_active_etfs()]:
        r = E.fetch_one(s, e, None, save=True)
        if r.status not in ("ok", "stale") or not r.rows:
            failed.append({"etf": e, "status": r.status, "reason": r.reason})
            continue
        rows_all += r.rows
        latest.append(r.asof)
        body = json.dumps(r.rows, ensure_ascii=False, default=str).encode("utf-8")
        p = snap_dir / f"{e}_{stamp}.json"
        if p.exists():
            raise RuntimeError(f"snapshot exists, refusing to overwrite {p}")
        p.write_bytes(body)
        manifest.append({"etf": e, "file": p.name, "sha256": sha256_bytes(body), "holdings_date": r.asof,
                         "rows": len(r.rows), "source_url": r.rows[0].get("source_url"),
                         "published_at": r.rows[0].get("published_at"), "fetched_at": r.rows[0].get("fetched_at")})
    mf = snap_dir / f"manifest_{stamp}.json"
    write_json(mf, {"snapshot_time": ctx["clock"].now().isoformat(), "files": manifest, "failed": failed})
    n = E.store_rows(rows_all) if rows_all else 0
    if not manifest:
        raise RuntimeError(f"no ETF holdings fetched ({len(failed)} failed)")
    return {"records": n, "latest_available_date": min(latest), "content_as_of": max(latest),
            "detail": {"etfs_ok": len(manifest), "etfs_failed": failed, "snapshot_manifest": str(mf.relative_to(ROOT))}}


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
            "latest_available_date": days[-1].isoformat(), "content_as_of": ctx["clock"].now().isoformat(),
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
    now = ctx["clock"].now().isoformat()
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
HEAVY = {"etf_holdings", "corporate_actions", "mops_material_info", "mops_revenue_first_seen"}


def refresh(trade_date: str, *, store: HistoryStore | None = None, fetchers: dict | None = None,
            ops_cfg: dict | None = None, clock: Clock | None = None, only: set | None = None,
            skip: set | None = None, allow_noncritical: bool = True, run_date: str | None = None) -> dict:
    ops_cfg = ops_cfg or load_ops_config()
    clock = clock or Clock()
    store = store or HistoryStore()
    fetchers = fetchers or DEFAULT_FETCHERS
    lg = ops_logger(trade_date, "refresh", ops_cfg)
    ctx = {"trade_date": trade_date, "store": store, "ops_cfg": ops_cfg, "clock": clock,
           "run_date": run_date or clock.now().strftime("%Y-%m-%d")}
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
            st.fetched_at = clock.now().isoformat()
            lag = stale_trading_days(st.latest_available_date, prev_weekdays(trade_date, 1)[0]) \
                if st.latest_available_date and len(st.latest_available_date) == 10 else None
            st.stale = lag is not None and lag > int(meta.get("max_stale_trading_days", 0))
            st.status = "STALE" if st.stale else "OK"
        except Exception as e:  # noqa: BLE001
            st.status = "FAILED"
            st.error = f"{type(e).__name__}: {e}"[:400]
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
