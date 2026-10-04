"""TAIFEX fetcher: 台指期 (TX) after-hours / night session (盤後交易時段) -> market_overnight.

Endpoint (official, public, no key):
    POST https://www.taifex.com.tw/cht/3/futDataDown
    form: down_type=1, commodity_id=TX, commodity_id2='', queryStartDate=YYYY/MM/DD, queryEndDate=YYYY/MM/DD
    -> CSV (MS950/cp950). Range must be <= ~1 month per request (longer ranges return an HTML error page).

CSV columns: 交易日期,契約,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,
             未沖銷契約數,最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,是否因訊息面暫停交易,交易時段,價差對單式委託成交量
交易時段 is 一般 (regular 08:45-13:45) or 盤後 (after-hours 15:00-05:00).

Date convention (verified on the data): a 盤後 row dated T is the session from the previous trading
day's 15:00 to T 05:00, i.e. TAIFEX already assigns the night session to the NEXT trading day T.
Evidence: on expiry day 2026-09-16 the 202609 contract still has a 盤後 row dated 09-16 (it cannot
trade after 13:30 on 09-16), and the 盤後 漲跌價 is measured from the previous day's 一般 結算價.

Output (symbol TXF_NIGHT, one row per Taiwan trade date T that has a night session):
  close/high/low/volume = 盤後 session of the near-month contract (smallest monthly YYYYMM contract with
                          a numeric close in that session; weekly 'W' contracts and spreads excluded)
  ret  = night close / (previous regular-session 結算價 SETTLEMENT price of the same contract) - 1.
         The reference settlement is taken from the 一般 row of the previous trade date when present in
         the downloaded data, else derived as close - 漲跌價 (TAIFEX's own reference, identical by construction).
  available_at = T 05:05+08:00 (session ends 05:00).
"""
from __future__ import annotations

import csv
import io
import re
import time
from datetime import date, datetime, timedelta

from agent.data.http import now_tpe
from agent.data.manifest import save_raw

AUTHORITY = "taifex"
SOURCE = "taifex_futDataDown"
PARSER_VERSION = "taifex-1"
URL = "https://www.taifex.com.tw/cht/3/futDataDown"
SYMBOL = "TXF_NIGHT"
AVAILABLE_TIME = "05:05:00"
SESSION_REGULAR = "一般"
SESSION_NIGHT = "盤後"

_last_post = [0.0]


def _num(x: str) -> float | None:
    x = (x or "").strip().replace(",", "")
    if x in ("", "-"):
        return None
    try:
        return float(x)
    except ValueError:
        return None


def parse_fut_csv(content: bytes) -> list[dict]:
    """Parse a futDataDown CSV into raw dicts (all contracts, both sessions)."""
    text = content.decode("cp950", errors="replace")
    if "<html" in text[:500].lower() or "<!doctype" in text[:500].lower():
        raise ValueError("TAIFEX returned HTML instead of CSV (range too long or bad query)")
    out = []
    reader = csv.reader(io.StringIO(text))
    next(reader, None)  # header
    for r in reader:
        if len(r) < 18 or not re.match(r"\d{4}/\d{2}/\d{2}$", r[0].strip()):
            continue
        out.append({
            "date": r[0].strip().replace("/", "-"),
            "commodity": r[1].strip(),
            "contract": r[2].strip(),
            "open": _num(r[3]), "high": _num(r[4]), "low": _num(r[5]), "close": _num(r[6]),
            "change": _num(r[7]), "volume": _num(r[9]), "settlement": _num(r[10]),
            "session": r[17].strip(),
        })
    return out


def _is_monthly(contract: str) -> bool:
    return bool(re.fullmatch(r"\d{6}", contract))


def build_night_rows(raw: list[dict]) -> list[dict]:
    """Raw futDataDown rows -> market_overnight rows for TXF_NIGHT (one per trade date)."""
    raw = [r for r in raw if _is_monthly(r["contract"])]
    reg = {(r["date"], r["contract"]): r for r in raw if r["session"] == SESSION_REGULAR}
    reg_dates = sorted({r["date"] for r in raw if r["session"] == SESSION_REGULAR})
    by_date: dict[str, list[dict]] = {}
    for r in raw:
        if r["session"] == SESSION_NIGHT and r["close"] is not None:
            by_date.setdefault(r["date"], []).append(r)
    rows = []
    for T in sorted(by_date):
        near = min(by_date[T], key=lambda r: r["contract"])
        prev_dates = [d for d in reg_dates if d < T]
        ref = None
        if prev_dates:
            pr = reg.get((prev_dates[-1], near["contract"]))
            if pr and pr["settlement"]:
                ref = pr["settlement"]
        if ref is None and near["change"] is not None:
            ref = near["close"] - near["change"]
        rows.append({
            "date": T, "symbol": SYMBOL, "close": near["close"],
            "ret": (near["close"] / ref - 1.0) if ref else None,
            "high": near["high"], "low": near["low"], "volume": near["volume"],
            "source": f"{SOURCE}:{near['contract']}",
            "available_at": f"{T}T{AVAILABLE_TIME}+08:00",
        })
    return rows


def _post(session, data: dict, *, min_interval: float, timeout: float = 60, retries: int = 3) -> tuple[bytes, datetime]:
    err: Exception | None = None
    for attempt in range(retries):
        wait = _last_post[0] + min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            r = session.post(URL, data=data, timeout=timeout)
            _last_post[0] = time.time()
            r.raise_for_status()
            parse_fut_csv(r.content)  # validates it is CSV
            return r.content, now_tpe()
        except Exception as e:  # noqa: BLE001
            _last_post[0] = time.time()
            err = e
            time.sleep(min_interval * (attempt + 2))
    raise RuntimeError(f"TAIFEX POST failed: {data}: {err}")


def _month_chunks(start: date, end: date):
    cur = start
    while cur <= end:
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        stop = min(end, nxt - timedelta(days=1))
        yield cur, stop
        cur = stop + timedelta(days=1)


def fetch_night_session(session, start: str, end: str, *, commodity: str = "TX",
                        min_interval: float = 3.0, save: bool = True, log=print) -> list[dict]:
    """Download TX daily quotes month by month and return TXF_NIGHT rows with start <= date <= end.
    Fetches 10 extra days before `start` so the first row has a previous settlement."""
    s = date.fromisoformat(start) - timedelta(days=10)
    e = date.fromisoformat(end)
    raw: list[dict] = []
    for a, b in _month_chunks(s, e):
        form = {"down_type": "1", "commodity_id": commodity, "commodity_id2": "",
                "queryStartDate": a.strftime("%Y/%m/%d"), "queryEndDate": b.strftime("%Y/%m/%d")}
        content, fetched = _post(session, form, min_interval=min_interval)
        part = parse_fut_csv(content)
        raw.extend(part)
        if log:
            log(f"[taifex] {a}..{b}: {len(part)} raw rows")
        if save:
            save_raw(b.strftime("%Y%m%d"), SOURCE, f"{commodity}_{a:%Y%m%d}_{b:%Y%m%d}.csv", content,
                     url=f"{URL}?commodity_id={commodity}&queryStartDate={a:%Y/%m/%d}&queryEndDate={b:%Y/%m/%d}",
                     fetched_at=fetched.isoformat(), content_as_of=f"{b.isoformat()}T13:45:00+08:00",
                     # file also holds b's regular session + settlement -> complete only after b 15:00
                     available_at=f"{b.isoformat()}T15:00:00+08:00", authority=AUTHORITY,
                     parser_version=PARSER_VERSION)
    return [r for r in build_night_rows(raw) if start <= r["date"] <= end]
