"""Active Share benchmark-source gate (P-5). Mode-aware; never guesses benchmark weights.

The official Active Share (>= 15% official, 30% internal target — both unchanged, config/competition.yaml and the
strategy buffers) is computed against the published top holdings of EVERY official active ETF. If those holdings
are missing or too old the number cannot be verified:
  COMPETITION     -> BLOCK  ACTIVE_SHARE_DATA_MISSING / ACTIVE_SHARE_DATA_STALE
  PRECOMPETITION  -> WARN   (paper runs continue; the compliance summary shows UNKNOWN)
Stale beyond ops.yaml preflight.etf_stale_days_block was already BLOCK in every mode and stays so.
Fixture stores (tests) may use their synthetic benchmark rows; the real store only counts real (non-synthetic) rows.
"""
from __future__ import annotations

from datetime import date


def source_status(store, trade_date: str, ops_cfg: dict, competition: bool, fixture: bool = False,
                  active_etfs: list[str] | None = None) -> dict:
    pf = ops_cfg["preflight"]
    e = store.load("etf_holdings")
    if not fixture and "synthetic" in e:
        e = e[~e["synthetic"].astype(bool)]
    e = e[e["date"] < trade_date]                       # PIT: only holdings published before T
    hard = "BLOCK" if competition else "WARN"
    if not len(e):
        return {"level": hard, "code": "ACTIVE_SHARE_DATA_MISSING", "detail": "no benchmark ETF holdings before T"}
    newest = e.groupby("etf")["date"].max()
    if fixture:                                         # synthetic test world: a static snapshot; age is meaningless
        return {"level": "PASS", "code": None, "detail": f"fixture benchmark: {newest.size} ETFs (synthetic snapshot)"}
    if active_etfs is None:
        from agent.engine.rules import load_rulebook
        active_etfs = list(load_rulebook().active_etfs)
    missing = sorted(set(active_etfs or []) - set(newest.index))
    age = (date.fromisoformat(trade_date) - date.fromisoformat(newest.min())).days
    detail = (f"{newest.size} ETFs with holdings; oldest latest-date {newest.min()} ({age} days); "
              f"missing {missing[:10] if missing else 'none'}")
    if age > pf["etf_stale_days_block"]:
        return {"level": "BLOCK", "code": "ACTIVE_SHARE_DATA_STALE", "detail": detail}
    if missing:
        return {"level": hard, "code": "ACTIVE_SHARE_DATA_MISSING", "detail": detail}
    if age > pf["etf_stale_days_warn"]:
        return {"level": "WARN", "code": "ACTIVE_SHARE_DATA_AGING", "detail": detail}
    return {"level": "PASS", "code": None, "detail": detail}


def source_check(store, trade_date: str, ops_cfg: dict, competition: bool, fixture: bool = False):
    from agent.ops.common import Check
    s = source_status(store, trade_date, ops_cfg, competition, fixture)
    return Check("active_share_source", s["level"], (f"{s['code']}: " if s["code"] else "") + s["detail"])


def result_gate(active_share_min, competition: bool) -> dict | None:
    """After the quant run: an UNKNOWN official Active Share may not be submitted in COMPETITION."""
    if active_share_min is not None:
        return None
    if competition:
        return {"level": "BLOCK", "code": "ACTIVE_SHARE_DATA_MISSING",
                "detail": "official Active Share could not be computed (benchmark holdings unavailable)"}
    return {"level": "WARN", "code": "ACTIVE_SHARE_UNKNOWN", "detail": "Active Share UNKNOWN (PRECOMPETITION: warning only)"}
