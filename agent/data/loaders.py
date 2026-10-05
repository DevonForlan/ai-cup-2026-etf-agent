"""History store (normalized parquet tables) + CSV / fixture loaders.

Every table carries `available_at` (ISO-8601 string, always +08:00) used by PITView.
Tables: daily_prices, institutional, monthly_revenue, corporate_actions, etf_holdings
"""
from __future__ import annotations

import json
import os
import time
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
                        "published_date": "str", "available_at": "str"},
    "corporate_actions": {"ex_date": "str", "ticker": "str", "cash_dividend": "float64",
                          "stock_dividend_per_share": "float64", "capital_change_ratio": "float64",
                          "action_type": "str", "source": "str", "available_at": "str"},
    # Active ETF holdings. weight = fraction of ETF NAV (0-1). `date` = holdings as-of date.
    "etf_holdings": {"date": "str", "etf": "str", "ticker": "str", "weight": "float64",
                     "rank": "int64", "shares": "float64", "source_url": "str", "published_at": "str",
                     "fetched_at": "str", "authority": "str", "is_stale": "bool",
                     "available_at": "str", "synthetic": "bool"},
    # Overnight / pre-open market data. `date` = the Taiwan TRADE DATE the value is used for
    # (e.g. US close of 2026-10-26 ET -> date 2026-10-27). symbol e.g. SPX, NDX, SOX, TSM, USDTWD, TXF_NIGHT
    # Company announcements (MOPS 重大訊息 etc.). text = subject/headline (+ body if available).
    # published_at = official 發言日期+時間 (+08:00); available_at = published_at (+ fetch lag if any).
    "material_info": {"event_key": "str", "ticker": "str", "published_at": "str", "subject": "str",
                      "body": "str", "source": "str", "source_url": "str", "authority": "str",
                      "available_at": "str"},
    "market_overnight": {"date": "str", "symbol": "str", "close": "float64", "ret": "float64",
                         "high": "float64", "low": "float64", "volume": "float64", "source": "str",
                         "available_at": "str"},
}
KEYS = {
    "daily_prices": ["date", "ticker"],
    "institutional": ["date", "ticker"],
    "monthly_revenue": ["ticker", "year", "month"],
    "corporate_actions": ["ex_date", "ticker"],
    "etf_holdings": ["date", "etf", "ticker"],
    "market_overnight": ["date", "symbol"],
    "material_info": ["event_key"],
}


def _coerce(df: pd.DataFrame, table: str) -> pd.DataFrame:
    sch = SCHEMAS[table]
    for c, t in sch.items():
        if c not in df.columns:
            df[c] = pd.NA
        if t == "str":
            # plain Python objects: much faster than Arrow strings for row-wise access
            df[c] = df[c].astype(object).where(df[c].notna(), None)
        elif t == "Int64":
            df[c] = pd.to_numeric(df[c], errors="coerce").round().astype("Int64")
        elif t == "bool":
            df[c] = df[c].map(lambda v: str(v).strip().lower() in ("true", "1", "yes") if pd.notna(v) else False).astype(bool)
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
                df = None
                for attempt in range(5):          # tolerate a concurrent writer (non-atomic legacy writers)
                    try:
                        df = pd.read_parquet(p)
                        break
                    except Exception:  # noqa: BLE001
                        if attempt == 4:
                            raise
                        time.sleep(1.0)
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
        tmp = self.path(table).with_suffix(f".tmp{os.getpid()}")
        allr.to_parquet(tmp, index=False)
        for attempt in range(10):                  # Windows: a concurrent reader may briefly lock the target
            try:
                os.replace(tmp, self.path(table))  # atomic on the same volume
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.5)
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
