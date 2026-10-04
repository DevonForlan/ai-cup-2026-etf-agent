"""History store (normalized parquet tables) + CSV / fixture loaders.

Every table carries `available_at` (ISO-8601 string, always +08:00) used by PITView.
Tables: daily_prices, institutional, monthly_revenue, corporate_actions, etf_holdings
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from agent.config import ROOT

HISTORY_DIR = ROOT / "data" / "history"

SCHEMAS: dict[str, dict[str, str]] = {
    "daily_prices": {"date": "str", "ticker": "str", "market": "str", "open": "float64",
                     "high": "float64", "low": "float64", "close": "float64", "volume": "Int64",
                     "amount": "Int64", "vwap": "float64", "available_at": "str"},
    "institutional": {"date": "str", "ticker": "str", "foreign_net": "Int64", "trust_net": "Int64",
                      "dealer_net": "Int64", "total_net": "Int64", "available_at": "str"},
    "monthly_revenue": {"ticker": "str", "year": "int64", "month": "int64", "revenue": "float64",
                        "available_at": "str"},
    "corporate_actions": {"ex_date": "str", "ticker": "str", "cash_dividend": "float64",
                          "stock_dividend_per_share": "float64", "available_at": "str"},
    "etf_holdings": {"date": "str", "etf": "str", "ticker": "str", "weight": "float64",
                     "rank": "int64", "available_at": "str", "synthetic": "bool"},
}
KEYS = {
    "daily_prices": ["date", "ticker"],
    "institutional": ["date", "ticker"],
    "monthly_revenue": ["ticker", "year", "month"],
    "corporate_actions": ["ex_date", "ticker"],
    "etf_holdings": ["date", "etf", "ticker"],
}


def _coerce(df: pd.DataFrame, table: str) -> pd.DataFrame:
    sch = SCHEMAS[table]
    for c, t in sch.items():
        if c not in df.columns:
            df[c] = pd.NA
        if t == "str":
            df[c] = df[c].astype("string")
        elif t == "Int64":
            df[c] = pd.to_numeric(df[c], errors="coerce").round().astype("Int64")
        elif t == "bool":
            df[c] = df[c].fillna(False).astype(bool)
        else:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(t)
    return df[list(sch)]


class HistoryStore:
    """Directory of parquet tables. Read access for features must go through PITView."""

    def __init__(self, root: Path | str = HISTORY_DIR):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, pd.DataFrame] = {}

    def path(self, table: str) -> Path:
        return self.root / f"{table}.parquet"

    def load(self, table: str) -> pd.DataFrame:
        if table not in self._cache:
            p = self.path(table)
            if p.exists():
                df = pd.read_parquet(p)
            else:
                df = pd.DataFrame(columns=list(SCHEMAS[table]))
            self._cache[table] = _coerce(df, table)
        return self._cache[table]

    def upsert(self, table: str, rows: list[dict] | pd.DataFrame) -> int:
        new = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
        if new.empty:
            return 0
        new = _coerce(new.copy(), table)
        cur = self.load(table)
        allr = pd.concat([cur, new], ignore_index=True) if len(cur) else new
        allr = allr.drop_duplicates(subset=KEYS[table], keep="last")
        allr = allr.sort_values(KEYS[table]).reset_index(drop=True)
        allr.to_parquet(self.path(table), index=False)
        self._cache[table] = allr
        return len(new)

    def dates(self, table: str = "daily_prices") -> list[str]:
        df = self.load(table)
        return sorted(df["date"].dropna().unique().tolist()) if len(df) else []


def load_csv_table(path: Path | str, table: str) -> pd.DataFrame:
    return _coerce(pd.read_csv(path, dtype=str), table)


def load_fixture_store(fixture_dir: Path | str, target: Path | str) -> HistoryStore:
    """Build a HistoryStore at `target` from CSV fixtures named <table>.csv."""
    fixture_dir = Path(fixture_dir)
    st = HistoryStore(target)
    for table in SCHEMAS:
        p = fixture_dir / f"{table}.csv"
        if p.exists():
            st.upsert(table, load_csv_table(p, table))
    return st


def load_json(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
