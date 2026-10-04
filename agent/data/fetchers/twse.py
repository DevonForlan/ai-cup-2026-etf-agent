"""TWSE fetchers (上市): daily quotes (MI_INDEX) and institutional flows (T86)."""
from __future__ import annotations

from agent.data import normalizers as N
from agent.data.http import get_bytes
from agent.data.manifest import save_raw

AUTHORITY = "twse"


def fetch_daily_quotes(session, cfg: dict, date: str, universe: set[str] | None,
                       avail_time: str) -> tuple[list[dict], dict]:
    """date = YYYY-MM-DD. Returns (rows, manifest entry dict)."""
    ymd = date.replace("-", "")
    url = cfg["endpoints"]["twse_mi_index"].format(yyyymmdd=ymd)
    b, fetched = get_bytes(session, url, min_interval=cfg["http"]["min_interval_sec"],
                           timeout=cfg["http"]["timeout_sec"], retries=cfg["http"]["retries"])
    e = save_raw(ymd, "twse_mi_index", "MI_INDEX.json", b, url=url, fetched_at=fetched.isoformat(),
                 content_as_of=f"{date}T13:30:00+08:00", available_at=f"{date}T{avail_time}:00+08:00",
                 authority=AUTHORITY, parser_version=N.PARSER_VERSION)
    return N.parse_twse_mi_index(b, date, universe), e.__dict__


def fetch_institutional(session, cfg: dict, date: str, universe: set[str] | None,
                        avail_time: str) -> tuple[list[dict], dict]:
    ymd = date.replace("-", "")
    url = cfg["endpoints"]["twse_t86"].format(yyyymmdd=ymd)
    b, fetched = get_bytes(session, url, min_interval=cfg["http"]["min_interval_sec"],
                           timeout=cfg["http"]["timeout_sec"], retries=cfg["http"]["retries"])
    e = save_raw(ymd, "twse_t86", "T86.json", b, url=url, fetched_at=fetched.isoformat(),
                 content_as_of=f"{date}T13:30:00+08:00", available_at=f"{date}T{avail_time}:00+08:00",
                 authority=AUTHORITY, parser_version=N.PARSER_VERSION)
    return N.parse_twse_t86(b, date, universe), e.__dict__
