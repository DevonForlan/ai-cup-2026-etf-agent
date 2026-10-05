"""Settlement ledger and providers.

data/settlement/YYYYMMDD_internal.json        our simulator's settlement (agent.sim.settle)
data/settlement/YYYYMMDD_official.json        the organiser's settlement, entered as DATA ONLY
data/settlement/YYYYMMDD_reconciliation.json  agent.ops.reconcile result

How the official settlement will be obtained is NOT confirmed (NC-1). Providers:
  ManualFileSettlementProvider  operator copies the back-office 庫存明細 into JSON/CSV (template below)
  ReplaySettlementProvider      internal ledger or a simulation run directory (dry runs / tests)
  FutureOfficialAPIProvider     stub — raises until the organiser documents an interface
Official data can only set holdings / cash / NAV for the next run's starting point; it can never touch
scores, strategy parameters or the stock selection logic.
"""
from __future__ import annotations

import csv
import json
from abc import ABC, abstractmethod
from decimal import Decimal
from pathlib import Path

from agent.config import D
from agent.ops.common import load_ops_config, ops_path, ymd, write_json
from agent.sim.models import Settlement

OFFICIAL_TEMPLATE = {
    "date": "YYYY-MM-DD",
    "source": "manual: back-office 庫存明細 / 淨值表 (describe exactly where it was copied from)",
    "entered_by": "operator name",
    "entered_at": "ISO-8601 +08:00",
    "holdings": {"2330": 17000},
    "cash": "123456789.00",
    "nav": "1000000000.00",
    "accrued_dividends": "0",
    "warnings": [],
}


def settlement_dir(cfg: dict | None = None) -> Path:
    return ops_path(cfg or load_ops_config(), "settlement_dir")


def path_for(date: str, kind: str, cfg: dict | None = None) -> Path:
    return settlement_dir(cfg) / f"{ymd(date)}_{kind}.json"


def save_internal(s: Settlement, cfg: dict | None = None) -> Path:
    p = path_for(s.date, "internal", cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    s.save(p)
    return p


def load_internal(date: str, cfg: dict | None = None) -> Settlement | None:
    p = path_for(date, "internal", cfg)
    return Settlement.load(p) if p.exists() else None


class SettlementProvider(ABC):
    name = "base"

    @abstractmethod
    def get(self, date: str) -> dict | None:
        """Official-format dict: {date, holdings{ticker:int}, cash, nav, accrued_dividends, warnings, source}"""


def normalize_official(d: dict) -> dict:
    return {"date": d["date"], "holdings": {str(k): int(v) for k, v in (d.get("holdings") or {}).items() if int(v) != 0},
            "cash": str(D(d["cash"])), "nav": str(D(d["nav"])) if d.get("nav") is not None else None,
            "accrued_dividends": str(D(d.get("accrued_dividends") or 0)), "warnings": list(d.get("warnings") or []),
            "source": d.get("source", "unknown"), "entered_by": d.get("entered_by"), "entered_at": d.get("entered_at")}


class ManualFileSettlementProvider(SettlementProvider):
    """Reads data/settlement/YYYYMMDD_official.json, or a CSV with rows ticker,shares plus special rows
    __CASH__,<amount> / __NAV__,<amount> / __ACCRUED__,<amount>."""
    name = "manual_file"

    def __init__(self, cfg: dict | None = None, csv_path: Path | None = None):
        self.cfg = cfg or load_ops_config()
        self.csv_path = csv_path

    def get(self, date: str) -> dict | None:
        p = path_for(date, "official", self.cfg)
        if p.exists():
            return normalize_official(json.loads(p.read_text(encoding="utf-8")))
        c = self.csv_path or settlement_dir(self.cfg) / f"{ymd(date)}_official.csv"
        if c.exists():
            from agent.ops.settlement_entry import parse_file
            raw, probs = parse_file(c)
            if probs:
                raise ValueError(f"{c}: " + "; ".join(probs))
            if raw.get("cash") in (None, ""):
                raise ValueError(f"{c}: missing __CASH__ row")
            if raw.get("date") and raw["date"] != date:
                raise ValueError(f"{c}: __DATE__ {raw['date']} != {date}")
            return normalize_official({"date": date, "holdings": {t: int(Decimal(v.replace(",", ""))) for t, v in raw["rows"]},
                                       "cash": raw["cash"].replace(",", ""),
                                       "nav": raw["nav"].replace(",", "") if raw.get("nav") else None,
                                       "accrued_dividends": str(raw.get("accrued") or 0).replace(",", ""),
                                       "warnings": raw.get("warnings") or [], "source": f"manual csv {c.name}"})
        return None


class ReplaySettlementProvider(SettlementProvider):
    """Uses an internal ledger or a sim run's settlement/<date>.json as the 'official' settlement."""
    name = "replay"

    def __init__(self, run_dir: Path | None = None, cfg: dict | None = None):
        self.run_dir = Path(run_dir) if run_dir else None
        self.cfg = cfg or load_ops_config()

    def settlement(self, date: str) -> Settlement | None:
        if self.run_dir:
            p = self.run_dir / "settlement" / f"{date}.json"
            return Settlement.load(p) if p.exists() else None
        return load_internal(date, self.cfg)

    def get(self, date: str) -> dict | None:
        s = self.settlement(date)
        if s is None:
            return None
        return normalize_official({"date": s.date, "holdings": s.holdings, "cash": s.cash, "nav": s.nav,
                                   "accrued_dividends": s.accrued_dividends,
                                   "warnings": [w["rule"] for w in s.warnings], "source": f"replay:{self.run_dir or 'internal'}"})


class FutureOfficialAPIProvider(SettlementProvider):
    name = "official_api"

    def get(self, date: str) -> dict | None:
        raise NotImplementedError("No official settlement API is documented (NC-1). Use ManualFileSettlementProvider.")


def save_official(d: dict, cfg: dict | None = None) -> Path:
    return write_json(path_for(d["date"], "official", cfg), normalize_official(d))


def apply_official(internal: Settlement, official: dict) -> Settlement:
    """Starting point for the next run = official holdings/cash/NAV + our own agent_state/history."""
    s = Settlement.from_dict(internal.to_dict())
    s.holdings = dict(official["holdings"])
    s.cash = D(official["cash"])
    if official.get("nav") is not None:
        s.nav = D(official["nav"])
    s.accrued_dividends = D(official.get("accrued_dividends") or 0)
    return s
