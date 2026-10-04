"""Configuration loading. Official rules, strategy buffers and unconfirmed rules
are kept in separate files and separate objects on purpose."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def load_yaml(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def D(x: Any) -> Decimal:
    """Exact decimal from int/str/float (floats via repr to keep JSON literal)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(repr(x))
    return Decimal(str(x))


@dataclass(frozen=True)
class OfficialRules:
    initial_cash: Decimal
    tsmc_ticker: str
    tsmc_max_weight: Decimal
    other_max_weight: Decimal
    cash_max_weight: Decimal
    cash_min: Decimal
    holdings_min: int
    holdings_max: int
    active_share_min: Decimal
    active_share_consecutive_days_dq: int
    buy_fee_rate: Decimal
    sell_fee_rate: Decimal
    transaction_tax_rate: Decimal
    lot_size: int
    max_daily_submissions: int
    warnings_to_dq: int
    price_drift_grace_trading_days: int
    submission_open: str
    submission_close: str
    c12_hold_tolerance_nav: Decimal
    schema_path: Path
    raw: dict = field(default_factory=dict, repr=False)

    def max_weight(self, ticker: str) -> Decimal:
        return self.tsmc_max_weight if ticker == self.tsmc_ticker else self.other_max_weight


def load_official_rules(path: str = "config/competition.yaml") -> OfficialRules:
    c = load_yaml(path)
    r = c["official_rules"]
    return OfficialRules(
        initial_cash=D(r["initial_cash"]),
        tsmc_ticker=str(r["tsmc_ticker"]),
        tsmc_max_weight=D(r["tsmc_max_weight"]),
        other_max_weight=D(r["other_max_weight"]),
        cash_max_weight=D(r["cash_max_weight"]),
        cash_min=D(r.get("cash_min", 0)),
        holdings_min=int(r["holdings_min"]),
        holdings_max=int(r["holdings_max"]),
        active_share_min=D(r["active_share_min"]),
        active_share_consecutive_days_dq=int(r["active_share_consecutive_days_dq"]),
        buy_fee_rate=D(r["buy_fee_rate"]),
        sell_fee_rate=D(r["sell_fee_rate"]),
        transaction_tax_rate=D(r["transaction_tax_rate"]),
        lot_size=int(r["lot_size"]),
        max_daily_submissions=int(r["max_daily_submissions"]),
        warnings_to_dq=int(r["warnings_to_dq"]),
        price_drift_grace_trading_days=int(r["price_drift_grace_trading_days"]),
        submission_open=r["submission_window"]["opens_prev_day"],
        submission_close=r["submission_window"]["closes"],
        c12_hold_tolerance_nav=D(c["dplan"]["c12_hold_tolerance_nav"]),
        schema_path=ROOT / c["dplan"]["schema_path"],
        raw=c,
    )


@dataclass(frozen=True)
class Assumptions:
    """Values used for unconfirmed rules. `unconfirmed` keeps the raw unknowns."""
    unconfirmed: dict
    active_share_mode: str
    cash_equal_25_allowed: bool
    fee_rounding_mode: str
    no_trade_execution_mode: str
    mdd_include_initial_nav: str
    c12_estimate_includes_fees: bool
    stock_dividend_odd_shares: str
    holdings_count_inclusive: bool

    def with_overrides(self, **kw) -> "Assumptions":
        d = self.__dict__.copy()
        d.update(kw)
        return Assumptions(**d)


def load_assumptions(path: str = "config/unconfirmed_rules.yaml") -> Assumptions:
    c = load_yaml(path)
    a = c["simulation_assumptions"]
    return Assumptions(
        unconfirmed=c["unconfirmed"],
        active_share_mode=str(a["active_share_mode"]),
        cash_equal_25_allowed=bool(a["cash_equal_25_allowed"]),
        fee_rounding_mode=str(a["fee_rounding_mode"]),
        no_trade_execution_mode=str(a["no_trade_execution_mode"]),
        mdd_include_initial_nav=str(a["mdd_include_initial_nav"]),
        c12_estimate_includes_fees=bool(a["c12_estimate_includes_fees"]),
        stock_dividend_odd_shares=str(a["stock_dividend_odd_shares"]),
        holdings_count_inclusive=bool(a["holdings_count_inclusive"]),
    )


def load_strategy(path: str = "config/strategy.yaml") -> dict:
    return load_yaml(path)


def load_data_sources(path: str = "config/data_sources.yaml") -> dict:
    return load_yaml(path)


def load_universe(path: str = "config/universe_150.csv") -> dict[str, dict]:
    """ticker -> {name, market('TWSE'|'TPEx')}"""
    p = ROOT / path
    out: dict[str, dict] = {}
    with open(p, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            out[row["ticker"].strip()] = {"name": row["name"].strip(), "market": row["market"].strip()}
    return out


def load_active_etfs(path: str = "config/active_etf_list.csv") -> list[dict]:
    p = ROOT / path
    with open(p, encoding="utf-8-sig") as f:
        return [
            {"etf": r["etf_code"].strip(), "name": r["name"].strip()}
            for r in csv.DictReader(f)
        ]
