"""MarketDataProvider interface. Live and Replay share the same interface; both return
normalized DataFrames (agent.data.loaders.SCHEMAS) filtered point-in-time.

Replay: reads data/history through PITView(as_of).
Live:   fetches the latest snapshot into data/raw/YYYYMMDD + data/history, then reads via PITView.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from agent.config import load_data_sources, load_universe
from agent.data.loaders import HistoryStore
from agent.data.pit import PITView


class MarketDataProvider(ABC):
    @abstractmethod
    def view(self, as_of: str) -> PITView: ...

    def get_daily_prices(self, as_of: str) -> pd.DataFrame:
        return self.view(as_of).prices()

    def get_institutional_flow(self, as_of: str) -> pd.DataFrame:
        return self.view(as_of).institutional()

    def get_margin(self, as_of: str) -> pd.DataFrame:
        raise NotImplementedError("margin data not in MVP-0")

    def get_monthly_revenue(self, as_of: str) -> pd.DataFrame:
        return self.view(as_of).monthly_revenue()

    def get_corporate_actions(self, as_of: str) -> pd.DataFrame:
        return self.view(as_of).table("corporate_actions")

    def get_etf_holdings(self, as_of: str) -> pd.DataFrame:
        return self.view(as_of).etf_holdings()


class ReplayProvider(MarketDataProvider):
    def __init__(self, store: HistoryStore):
        self.store = store

    def view(self, as_of: str) -> PITView:
        return PITView(self.store, as_of)


class LiveProvider(MarketDataProvider):
    """Fetches T-1 data for the trade date, then serves PIT views. Network errors are reported,
    not raised, so the daily run can fall back to cached history."""

    def __init__(self, store: HistoryStore):
        self.store = store
        self.errors: list[str] = []

    def refresh(self, prev_trade_date: str) -> None:
        from agent.data.fetchers import tpex, twse
        from agent.data.http import make_session
        cfg = load_data_sources()
        av = cfg["availability"]
        uni = load_universe()
        tw = {t for t, v in uni.items() if v["market"] == "TWSE"}
        ot = {t for t, v in uni.items() if v["market"] == "TPEx"}
        s = make_session(cfg["http"]["relax_x509_strict"])
        d = prev_trade_date
        for name, fn, univ, key, table in (
            ("twse prices", twse.fetch_daily_quotes, tw, "daily_prices", "daily_prices"),
            ("tpex prices", tpex.fetch_daily_quotes, ot, "daily_prices", "daily_prices"),
            ("twse insti", twse.fetch_institutional, tw, "institutional", "institutional"),
            ("tpex insti", tpex.fetch_institutional, ot, "institutional", "institutional"),
        ):
            try:
                rows, _ = fn(s, cfg, d, univ, av[key])
                self.store.upsert(table, [dict(r, available_at=f"{d}T{av[key]}:00+08:00") for r in rows])
            except Exception as e:  # noqa: BLE001
                self.errors.append(f"{name} {d}: {e}")

    def view(self, as_of: str) -> PITView:
        return PITView(self.store, as_of)
