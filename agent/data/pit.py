"""Point-in-time view. All feature code must read data ONLY through PITView.

A row is visible iff row.available_at <= as_of. Rows whose business date is after the as_of
date are additionally rejected (defence in depth). `LeakageError` is raised if a filtered
result still contains future rows (should be impossible; it guards future refactors).
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from agent.data.loaders import HistoryStore

DATE_COL = {"daily_prices": "date", "institutional": "date", "corporate_actions": None,
            "monthly_revenue": None, "etf_holdings": "date",
            "market_overnight": "date", "material_info": None}


class LeakageError(RuntimeError):
    pass


def _check_iso(ts: str) -> str:
    dt = datetime.fromisoformat(ts)
    if dt.utcoffset() is None or dt.utcoffset().total_seconds() != 8 * 3600:
        raise ValueError(f"as_of must be ISO-8601 with +08:00, got {ts!r}")
    return dt.isoformat()


class PITView:
    def __init__(self, store: HistoryStore, as_of: str):
        self.store = store
        self.as_of = _check_iso(as_of)
        self.as_of_date = self.as_of[:10]
        self.reads: list[dict] = []           # audit trail of what was read

    def table(self, name: str) -> pd.DataFrame:
        df = self.store.load(name)
        if len(df) == 0:
            return df.copy()
        av = df["available_at"].astype("string")
        bad_fmt = av.notna() & ~av.str.endswith("+08:00")
        if bad_fmt.any():
            raise LeakageError(f"{name}: available_at must be +08:00 ISO strings")
        out = df[av.notna() & (av <= self.as_of)]
        dc = DATE_COL.get(name)
        if dc:
            out = out[out[dc] <= self.as_of_date]
        if len(out) and (out["available_at"].max() > self.as_of):
            raise LeakageError(f"{name}: row with available_at > as_of leaked")
        self.reads.append({"table": name, "rows": int(len(out)),
                           "max_available_at": None if not len(out) else str(out["available_at"].max())})
        return out.copy()

    def prices(self) -> pd.DataFrame:
        return self.table("daily_prices")

    def institutional(self) -> pd.DataFrame:
        return self.table("institutional")

    def monthly_revenue(self) -> pd.DataFrame:
        return self.table("monthly_revenue")

    def etf_holdings(self) -> pd.DataFrame:
        return self.table("etf_holdings")
