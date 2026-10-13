"""Active Share vs each official active ETF's top-10 holdings (辦法 §六(十三)).

    Active Share = 1/2 × Σ |W_i(portfolio) − W_i(benchmark)|

The definition of W_i is UNCONFIRMED (NC-2). We compute every interpretation and never claim
which one is official:
  NAV_WEIGHT        portfolio top-10 (weight of NAV) vs ETF top-10 (weight of ETF NAV), union
  TOP10_NORMALIZED  both top-10 sets renormalised to sum 1
  FULL_PORTFOLIO    all portfolio holdings (weight of NAV) vs ETF top-10 (weight of ETF NAV)
  UNKNOWN           = evaluate all of the above and use the minimum (conservative gate)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from agent.config import D


class ActiveShareMode(str, Enum):
    NAV_WEIGHT = "NAV_WEIGHT"
    TOP10_NORMALIZED = "TOP10_NORMALIZED"
    FULL_PORTFOLIO = "FULL_PORTFOLIO"
    UNKNOWN = "UNKNOWN"


CONCRETE_MODES = (ActiveShareMode.NAV_WEIGHT, ActiveShareMode.TOP10_NORMALIZED,
                  ActiveShareMode.FULL_PORTFOLIO)


def _top_n(w: dict[str, Decimal], n: int = 10) -> dict[str, Decimal]:
    items = sorted(w.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    return dict(items)


def _norm(w: dict[str, Decimal]) -> dict[str, Decimal]:
    s = sum((w[k] for k in sorted(w)), Decimal(0))
    return {k: v / s for k, v in w.items()} if s > 0 else dict(w)


def active_share(port: dict[str, Decimal], bench: dict[str, Decimal]) -> Decimal:
    keys = sorted(set(port) | set(bench))          # sorted: deterministic summation order (hash seed independent)
    return sum((abs(port.get(k, Decimal(0)) - bench.get(k, Decimal(0))) for k in keys),
               Decimal(0)) / 2


def active_share_mode(portfolio_w: dict, etf_top10_w: dict, mode: ActiveShareMode) -> Decimal:
    p = {k: D(v) for k, v in portfolio_w.items() if D(v) > 0}
    b = _top_n({k: D(v) for k, v in etf_top10_w.items() if D(v) > 0}, 10)
    if mode == ActiveShareMode.NAV_WEIGHT:
        return active_share(_top_n(p), b)
    if mode == ActiveShareMode.TOP10_NORMALIZED:
        return active_share(_norm(_top_n(p)), _norm(b))
    if mode == ActiveShareMode.FULL_PORTFOLIO:
        return active_share(p, b)
    raise ValueError("UNKNOWN is not a concrete mode")


@dataclass
class ActiveShareResult:
    mode_used: str
    minimum_active_share: Decimal | None
    benchmark_ticker: str | None
    min_by_mode: dict[str, Decimal | None]
    per_etf: dict[str, dict[str, Decimal]] = field(default_factory=dict)
    missing_benchmarks: list[str] = field(default_factory=list)
    benchmarks_data_date: str | None = None
    benchmarks_synthetic: bool = False
    cash_term: str | None = None          # official mode only: INCLUDED / NEED_CONFIRMATION / EXCLUDED_BY_CONFIG


def compute_active_share(portfolio_w: dict, etf_holdings: dict[str, dict],
                         official_etfs: list[str], mode: ActiveShareMode | str = ActiveShareMode.UNKNOWN,
                         data_date: str | None = None, synthetic: bool = False) -> ActiveShareResult:
    mode = ActiveShareMode(mode)
    modes = CONCRETE_MODES if mode == ActiveShareMode.UNKNOWN else (mode,)
    per_etf: dict[str, dict[str, Decimal]] = {}
    missing = []
    for etf in official_etfs:
        h = etf_holdings.get(etf)
        if not h:
            missing.append(etf)
            continue
        per_etf[etf] = {m.value: active_share_mode(portfolio_w, h, m) for m in modes}
    min_by_mode: dict[str, Decimal | None] = {}
    for m in modes:
        vals = [v[m.value] for v in per_etf.values()]
        min_by_mode[m.value] = min(vals) if vals else None
    best = None
    for etf, v in per_etf.items():
        for m, x in v.items():
            if best is None or x < best[0]:
                best = (x, etf)
    return ActiveShareResult(mode.value, best[0] if best else None, best[1] if best else None,
                             min_by_mode, per_etf, missing, data_date, synthetic)


# ----------------------------------------------------------------------------- official rule (confirmed)
# Sources: 比賽辦法_1005更新 §六(十三) (top-15 vs each active ETF's top-15, < 15% = violation, 2 consecutive
# trading days -> DQ) + organiser e-mail 2026-10-07 (W_i = weight of total NAV, cash included, union of both
# top-15 sets, compare against every official active ETF). The legacy functions above are kept unchanged:
# Quant Core v1's internal 30% guard still uses them (decision path frozen).
OFFICIAL_MODE = "OFFICIAL_TOP15_NAV"
CASH_KEY = "CASH"


def official_active_share(port_nav_w: dict, bench_nav_w: dict, top_n: int = 15,
                          port_cash: Decimal | None = None, bench_cash: Decimal | None = None,
                          include_cash: bool = True) -> tuple[Decimal, str]:
    """1/2 x sum |Wp - Wb| over the union of both top-N stock sets, weights as fraction of NAV.
    Cash term: added only when BOTH cash weights are known. A benchmark cash weight is not disclosed by the
    issuers -> the term is left out (status NEED_CONFIRMATION). Leaving out a non-negative term gives the
    LOWER value, i.e. the conservative side of the 15% gate; it is never filled with a guessed 0."""
    p = _top_n({k: D(v) for k, v in port_nav_w.items() if k != CASH_KEY and D(v) > 0}, top_n)
    b = _top_n({k: D(v) for k, v in bench_nav_w.items() if k != CASH_KEY and D(v) > 0}, top_n)
    value = active_share(p, b)
    if not include_cash:
        return value, "EXCLUDED_BY_CONFIG"
    if port_cash is None or bench_cash is None:
        return value, "NEED_CONFIRMATION"
    return value + abs(D(port_cash) - D(bench_cash)) / 2, "INCLUDED"


def compute_official_active_share(portfolio_nav_w: dict, etf_holdings: dict[str, dict], official_etfs: list[str],
                                  top_n: int = 15, port_cash: Decimal | None = None,
                                  bench_cash: dict[str, Decimal] | None = None, include_cash: bool = True,
                                  data_date: str | None = None, synthetic: bool = False) -> ActiveShareResult:
    """Every official active ETF is compared one by one; the minimum is the gate value."""
    per_etf: dict[str, dict[str, Decimal]] = {}
    missing, cash_status = [], set()
    for etf in official_etfs:
        h = etf_holdings.get(etf)
        if not h:
            missing.append(etf)
            continue
        v, cs = official_active_share(portfolio_nav_w, h, top_n, port_cash, (bench_cash or {}).get(etf),
                                      include_cash)
        per_etf[etf] = {OFFICIAL_MODE: v}
        cash_status.add(cs)
    best = min(((v[OFFICIAL_MODE], e) for e, v in per_etf.items()), default=None)
    return ActiveShareResult(OFFICIAL_MODE, best[0] if best else None, best[1] if best else None,
                             {OFFICIAL_MODE: best[0] if best else None}, per_etf, missing, data_date, synthetic,
                             ",".join(sorted(cash_status)) or None)
