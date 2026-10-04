"""Overnight market data (US indices, TSMC ADR, USD/TWD, TAIFEX night session) -> market_overnight.

Provider abstraction: every source implements `OvernightProvider.get(symbols, start, end)` and returns
market_overnight rows whose `date` is the Taiwan TRADE DATE T the value is used for. `start`/`end`
are Taiwan trade dates (inclusive). `CompositeProvider` routes each symbol to an ordered list of
providers (first one that returns rows wins), so another vendor can be plugged in by adding a class
and a route entry.

Date mapping
  US (SPX/NDX/IXIC/SOX/TSM): US trading day D (America/New_York) closes 16:00 ET = 04:00 Taipei (EDT)
    or 05:00 Taipei (EST) on the next calendar day. T = next Taiwan weekday after D (Fri -> Mon).
    available_at = T 05:30+08:00 (conservative; asserted to be after the actual close incl. DST).
  USDTWD (CBC / Taipei Forex interbank close): observation day D (Taipei business day, close 16:00,
    CBC posts 16:00-17:00). T = next weekday after D; available_at = D 17:00+08:00 (< T 08:00).
  ret = close / previous observation close - 1, computed on the source series BEFORE mapping (so it is
    the 1-observation return of the source; a skipped TW holiday does not create a double count).
  TXF_NIGHT: see agent/data/fetchers/taifex.py.

Sources
  fred   : FRED fredgraph.csv (St. Louis Fed; free, no key). SP500 -> SPX, NASDAQ100 -> NDX,
           NASDAQCOM -> IXIC. Close only. NOTE: FRED's WAF resets connections for browser-like UAs, the
           session uses the plain python-requests UA. DEXTAUS (USD/TWD) is NOT used: it is published
           weekly (H.10) with ~1 week lag, useless for a pre-open signal.
  cbc    : Central Bank of the ROC (www.cbc.gov.tw lp-645-1) NTD/USD interbank closing rate
           (data: Taipei Forex Inc.). Official, free.
  yahoo  : query1.finance.yahoo.com v8 chart JSON. UNOFFICIAL / vendor, ToS risk, may rate-limit;
           used only for symbols without an official free source (SOX, TSM) and as fallback.
  (Stooq CSV was evaluated but now serves a JavaScript bot challenge -> not usable headless.)

CLI: python agent/data/overnight.py --start 2024-03-01 --end 2026-10-02 [--taifex] [--no-us]
"""
from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__":  # allow `python agent/data/overnight.py`
    # drop agent/data from sys.path (its http.py would shadow the stdlib `http` package)
    _here = Path(__file__).resolve().parent
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _here]
    sys.path.insert(0, str(_here.parents[1]))

import argparse
import csv
import io
import json
import re
from abc import ABC, abstractmethod
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from agent.data.http import get_bytes, make_session
from agent.data.manifest import save_raw

NY = ZoneInfo("America/New_York")
TPE = ZoneInfo("Asia/Taipei")
PARSER_VERSION = "overnight-1"
US_SYMBOLS = ["SPX", "NDX", "IXIC", "SOX", "TSM"]
REQUIRED_SYMBOLS = ["SPX", "NDX", "SOX", "TSM", "USDTWD"]
US_AVAILABLE_TIME = dtime(5, 30)
US_CLOSE_ET = dtime(16, 0)
CBC_AVAILABLE_TIME = "17:00:00"


# ----------------------------------------------------------------------------- date mapping
def next_weekday(d: date) -> date:
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return n


def us_close_taipei(d: date) -> datetime:
    """US regular close of US day D, expressed in Asia/Taipei (DST aware)."""
    return datetime.combine(d, US_CLOSE_ET, tzinfo=NY).astimezone(TPE)


def map_us_day(d: date) -> tuple[str, str]:
    """US trading day D -> (Taiwan trade date T, available_at ISO +08:00)."""
    T = next_weekday(d)
    avail = datetime.combine(T, US_AVAILABLE_TIME, tzinfo=TPE)
    close = us_close_taipei(d)
    if close > avail:  # cannot happen for a 16:00 ET close, guard against config changes
        raise AssertionError(f"US close {close} after available_at {avail}")
    return T.isoformat(), avail.isoformat()


def map_tw_fx_day(d: date) -> tuple[str, str]:
    """Taipei FX close of day D -> (T, available_at). Value is the latest one strictly before T 08:00."""
    return next_weekday(d).isoformat(), f"{d.isoformat()}T{CBC_AVAILABLE_TIME}+08:00"


def to_rows(symbol: str, source: str, obs: list[dict], mapper, start: str, end: str) -> list[dict]:
    """obs: [{'d': date, 'close', 'high'?, 'low'?, 'volume'?, 'ret_close'?}] sorted or not.
    ret uses 'ret_close' (e.g. dividend-adjusted) when present, else close."""
    obs = sorted([o for o in obs if o.get("close") is not None], key=lambda o: o["d"])
    rows, prev = [], None
    for o in obs:
        rc = o.get("ret_close") if o.get("ret_close") is not None else o["close"]
        ret = (rc / prev - 1.0) if prev else None
        prev = rc
        T, avail = mapper(o["d"])
        if start <= T <= end:
            rows.append({"date": T, "symbol": symbol, "close": o["close"], "ret": ret,
                         "high": o.get("high"), "low": o.get("low"), "volume": o.get("volume"),
                         "source": source, "available_at": avail})
    return rows


# ----------------------------------------------------------------------------- parsers
def parse_fred_csv(content: bytes) -> list[dict]:
    out = []
    rdr = csv.reader(io.StringIO(content.decode("utf-8")))
    next(rdr, None)
    for r in rdr:
        if len(r) >= 2 and r[1].strip() not in ("", "."):
            out.append({"d": date.fromisoformat(r[0].strip()), "close": float(r[1])})
    return out


_CBC_RE = re.compile(r"<span>(\d{4})/(\d{2})/(\d{2})</span></td>\s*<td[^>]*><span>([\d.]+)</span>")


def parse_cbc_html(content: bytes) -> list[dict]:
    t = content.decode("utf-8", errors="replace")
    return [{"d": date(int(y), int(m), int(dd)), "close": float(v)} for y, m, dd, v in _CBC_RE.findall(t)]


def parse_yahoo_chart(content: bytes, now: datetime | None = None) -> list[dict]:
    """v8 chart JSON -> daily bars keyed by exchange-local date. Drops a bar whose session has not
    closed yet (live fetch during the US session)."""
    j = json.loads(content)
    res = (j.get("chart") or {}).get("result") or []
    if not res:
        raise ValueError(f"yahoo chart: no result ({(j.get('chart') or {}).get('error')})")
    r = res[0]
    tz = ZoneInfo(r["meta"].get("exchangeTimezoneName") or "America/New_York")
    q = r["indicators"]["quote"][0]
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    now = now or datetime.now(timezone.utc)
    out = []
    for i, ts in enumerate(r.get("timestamp") or []):
        d = datetime.fromtimestamp(ts, tz).date()
        if datetime.combine(d, US_CLOSE_ET, tzinfo=NY) > now:
            continue
        c = q["close"][i]
        if c is None:
            continue
        out.append({"d": d, "close": float(c), "high": q["high"][i], "low": q["low"][i],
                    "volume": q["volume"][i] or None,  # indices report 0
                    "ret_close": adj[i] if adj else None})
    return out


# ----------------------------------------------------------------------------- providers
class OvernightProvider(ABC):
    """Interface. `get` returns market_overnight rows (date = Taiwan trade date)."""
    name: str = "abstract"
    symbols: dict[str, str] = {}          # our symbol -> source code

    def supports(self, symbol: str) -> bool:
        return symbol in self.symbols

    @abstractmethod
    def get(self, symbols: list[str], start: str, end: str) -> list[dict]:
        ...


class _HttpProvider(OvernightProvider):
    authority = "other"
    min_interval = 3.0

    def __init__(self, session: requests.Session | None = None, save: bool = True, log=print):
        self.session = session or make_session()
        self.save = save
        self.log = log or (lambda *_: None)

    def _fetch(self, url: str, params: dict, raw_name: str, end: str) -> bytes:
        b, fetched = get_bytes(self.session, url, params=params, min_interval=self.min_interval, timeout=60)
        if self.save:
            save_raw(end.replace("-", ""), f"overnight_{self.name}", raw_name, b,
                     url=requests.Request("GET", url, params=params).prepare().url, fetched_at=fetched.isoformat(),
                     content_as_of=fetched.isoformat(), available_at=fetched.isoformat(),
                     authority=self.authority, parser_version=PARSER_VERSION)
        return b


def _obs_start(start: str, days: int = 14) -> date:
    return date.fromisoformat(start) - timedelta(days=days)


class FredProvider(_HttpProvider):
    name = "fred"
    symbols = {"SPX": "SP500", "NDX": "NASDAQ100", "IXIC": "NASDAQCOM"}
    URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        # FRED's WAF tarpits / resets browser-like UAs; the default requests UA works.
        self.session.headers["User-Agent"] = requests.utils.default_user_agent()

    def get(self, symbols, start, end):
        rows = []
        for s in symbols:
            sid = self.symbols[s]
            b = self._fetch(self.URL, {"id": sid, "cosd": _obs_start(start).isoformat(), "coed": end},
                            f"{sid}.csv", end)
            obs = parse_fred_csv(b)
            self.log(f"[fred] {s}<-{sid}: {len(obs)} obs")
            rows += to_rows(s, f"fred:{sid}", obs, map_us_day, start, end)
        return rows


class CbcFxProvider(_HttpProvider):
    name = "cbc"
    symbols = {"USDTWD": "lp-645-1"}
    URL = "https://www.cbc.gov.tw/tw/lp-645-1-{page}-{size}.html"
    PAGE_SIZE = 60   # the page offers 20/40/60; other sizes render a chart page without the table

    def get(self, symbols, start, end):
        if "USDTWD" not in symbols:
            return []
        lo = _obs_start(start)
        obs: dict[date, dict] = {}
        for page in range(1, 400):
            url = self.URL.format(page=page, size=self.PAGE_SIZE)
            b = self._fetch(url, {}, f"lp-645-1-{page}-{self.PAGE_SIZE}.html", end)
            part = parse_cbc_html(b)
            if not part and page == 1:
                raise ValueError("CBC page layout changed: no NTD/USD rows parsed")
            for o in part:
                obs[o["d"]] = o
            if not part or min(o["d"] for o in part) < lo:
                break
        self.log(f"[cbc] USDTWD: {len(obs)} obs")
        return to_rows("USDTWD", "cbc:lp-645-1", list(obs.values()), map_tw_fx_day, start, end)


class YahooChartProvider(_HttpProvider):
    """UNOFFICIAL Yahoo Finance chart API (vendor ToS risk). Fallback / symbols without free official data."""
    name = "yahoo"
    authority = "vendor"
    symbols = {"SPX": "^GSPC", "NDX": "^NDX", "IXIC": "^IXIC", "SOX": "^SOX", "TSM": "TSM"}
    URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"

    def get(self, symbols, start, end):
        rows = []
        p1 = int(datetime.combine(_obs_start(start), dtime(0), tzinfo=timezone.utc).timestamp())
        p2 = int(datetime.combine(date.fromisoformat(end) + timedelta(days=1), dtime(0), tzinfo=timezone.utc).timestamp())
        for s in symbols:
            ys = self.symbols[s]
            b = self._fetch(self.URL.format(sym=ys), {"period1": p1, "period2": p2, "interval": "1d",
                                                       "events": "history"}, f"{ys.strip('^')}.json", end)
            obs = parse_yahoo_chart(b)
            self.log(f"[yahoo] {s}<-{ys}: {len(obs)} obs")
            rows += to_rows(s, f"yahoo_unofficial:{ys}", obs, map_us_day, start, end)
        return rows


class CompositeProvider(OvernightProvider):
    """Routes each symbol to an ordered provider list; records failures in `self.status`."""
    name = "composite"

    def __init__(self, routes: dict[str, list[OvernightProvider]], log=print):
        self.routes = routes
        self.symbols = {s: "composite" for s in routes}
        self.status: dict[str, str] = {}
        self.log = log or (lambda *_: None)

    def get(self, symbols, start, end):
        rows = []
        for s in symbols:
            for p in self.routes.get(s, []):
                try:
                    got = p.get([s], start, end)
                except Exception as e:  # noqa: BLE001
                    self.status[s] = f"{p.name} failed: {e}"
                    self.log(f"[overnight] {s}: {p.name} failed: {e}")
                    continue
                if got:
                    rows += got
                    self.status[s] = f"ok via {p.name}"
                    break
                self.status[s] = f"{p.name} returned no rows"
            else:
                self.status.setdefault(s, "no provider configured")
                self.log(f"[overnight] {s}: NOT AVAILABLE from any configured free source ({self.status[s]})")
        return rows


def default_provider(save: bool = True, log=print) -> CompositeProvider:
    fred, cbc, yahoo = FredProvider(save=save, log=log), CbcFxProvider(save=save, log=log), YahooChartProvider(save=save, log=log)
    return CompositeProvider({"SPX": [fred, yahoo], "NDX": [fred, yahoo], "IXIC": [fred, yahoo],
                              "SOX": [yahoo], "TSM": [yahoo], "USDTWD": [cbc]}, log=log)


# ----------------------------------------------------------------------------- coverage + CLI
def weekdays(start: str, end: str) -> list[str]:
    d, e, out = date.fromisoformat(start), date.fromisoformat(end), []
    while d <= e:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def coverage(df, start: str, end: str) -> list[dict]:
    wd = set(weekdays(start, end))
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    out = []
    for sym, g in df.groupby("symbol"):
        srcs = sorted({str(x).split(":")[0] for x in g["source"].dropna()})
        out.append({"symbol": sym, "source": ",".join(srcs), "first": g["date"].min(), "last": g["date"].max(),
                    "rows": len(g), "missing_weekdays": len(wd - set(g["date"]))})
    return out


def print_coverage(cov: list[dict]) -> None:
    hdr = f"{'symbol':<10} {'source':<22} {'first':<11} {'last':<11} {'rows':>5} {'missing_wd':>10}"
    print(hdr)
    print("-" * len(hdr))
    for c in cov:
        print(f"{c['symbol']:<10} {c['source']:<22} {c['first']:<11} {c['last']:<11} {c['rows']:>5} {c['missing_weekdays']:>10}")


def main(argv=None) -> int:
    from agent.data.fetchers.taifex import fetch_night_session
    from agent.data.loaders import HistoryStore

    ap = argparse.ArgumentParser(description="Backfill market_overnight (US/ADR/FX + TAIFEX night).")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--taifex", action="store_true", help="also fetch TAIFEX TX night session")
    ap.add_argument("--no-us", action="store_true", help="skip US/ADR/FX providers")
    ap.add_argument("--symbols", default="SPX,NDX,IXIC,SOX,TSM,USDTWD")
    ap.add_argument("--no-save-raw", action="store_true")
    a = ap.parse_args(argv)
    st = HistoryStore()
    if not a.no_us:
        prov = default_provider(save=not a.no_save_raw)
        rows = prov.get([s.strip() for s in a.symbols.split(",") if s.strip()], a.start, a.end)
        print(f"[overnight] upsert {st.upsert('market_overnight', rows)} rows")
        for s, msg in prov.status.items():
            print(f"  {s}: {msg}")
    if a.taifex:
        rows = fetch_night_session(make_session(), a.start, a.end, save=not a.no_save_raw)
        print(f"[taifex] upsert {st.upsert('market_overnight', rows)} rows")
    print_coverage(coverage(st.load("market_overnight"), a.start, a.end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
