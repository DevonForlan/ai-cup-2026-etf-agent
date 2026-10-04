"""TPEx fetchers (上櫃): daily quotes and institutional flows."""
from __future__ import annotations

from agent.data import normalizers as N
from agent.data.http import get_bytes
from agent.data.manifest import save_raw

AUTHORITY = "tpex"


def _fmt(url_t: str, date: str) -> str:
    y, m, d = date.split("-")
    return url_t.format(yyyy=y, mm=m, dd=d)


def fetch_daily_quotes(session, cfg: dict, date: str, universe: set[str] | None,
                       avail_time: str) -> tuple[list[dict], dict]:
    url = _fmt(cfg["endpoints"]["tpex_daily_quotes"], date)
    b, fetched = get_bytes(session, url, min_interval=cfg["http"]["min_interval_sec"],
                           timeout=cfg["http"]["timeout_sec"], retries=cfg["http"]["retries"])
    e = save_raw(date.replace("-", ""), "tpex_daily_quotes", "dailyQuotes.json", b, url=url,
                 fetched_at=fetched.isoformat(), content_as_of=f"{date}T13:30:00+08:00",
                 available_at=f"{date}T{avail_time}:00+08:00", authority=AUTHORITY,
                 parser_version=N.PARSER_VERSION)
    return N.parse_tpex_daily_quotes(b, date, universe), e.__dict__


def fetch_institutional(session, cfg: dict, date: str, universe: set[str] | None,
                        avail_time: str) -> tuple[list[dict], dict]:
    url = _fmt(cfg["endpoints"]["tpex_insti"], date)
    b, fetched = get_bytes(session, url, min_interval=cfg["http"]["min_interval_sec"],
                           timeout=cfg["http"]["timeout_sec"], retries=cfg["http"]["retries"])
    e = save_raw(date.replace("-", ""), "tpex_insti", "dailyTrade.json", b, url=url,
                 fetched_at=fetched.isoformat(), content_as_of=f"{date}T13:30:00+08:00",
                 available_at=f"{date}T{avail_time}:00+08:00", authority=AUTHORITY,
                 parser_version=N.PARSER_VERSION)
    return N.parse_tpex_insti(b, date, universe), e.__dict__
