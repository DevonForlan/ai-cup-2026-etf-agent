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
