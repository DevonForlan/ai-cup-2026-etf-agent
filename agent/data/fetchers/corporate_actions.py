"""Corporate actions (除權息 / 減資 / 變更面額) from official TWSE + TPEx public pages.

Sources (all public, no credentials):
  TWSE 除權除息計算結果表 (list)      /rwd/zh/exRight/TWT49U?startDate=YYYYMMDD&endDate=YYYYMMDD&response=json
  TWSE 除權息明細 (per event)          /rwd/zh/exRight/TWT49UDetail?STK_NO=XXXX&T1=YYYYMMDD&response=json
  TWSE 減資恢復買賣參考價格            /rwd/zh/reducation/TWTAUU?startDate=..&endDate=..&response=json
  TWSE 減資明細 (per event)            /rwd/zh/reducation/TWTAVUDetail?STK_NO=XXXX&FILE_DATE=YYYYMMDD&response=json
  TWSE 變更股票面額恢復買賣參考價格    /rwd/zh/change/TWTB8U?startDate=..&endDate=..&response=json
  TPEx 除權除息計算結果表              https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate=YYYY/MM/DD&endDate=YYYY/MM/DD&response=json
  TPEx 減資恢復買賣參考價格            https://www.tpex.org.tw/www/zh-tw/bulletin/revivt?startDate=..&endDate=..&response=json
  (TPEx par-value change list: no public JSON endpoint found -> not covered.)

Output table `corporate_actions`, one row per (ex_date, ticker):
  cash_dividend             TWD per (old) share received in cash. For capital reductions this is the
                            cash returned per old share (退還股款) + any merged cash dividend.
  stock_dividend_per_share  bonus shares received per share held (每千股無償配股 / 1000).
                            TWSE: from TWT49UDetail field "A. 按普通股股東持股比例每千股無償配股" (the
                            holder entitlement). If the detail is unavailable, derived from the reference
                            price formula  ref = (P - cash) / (1 + s)  ->  s = (P - cash) / (P - 權值+息值) - 1
                            (pure 權 events only, cash = 0; 權值+息值 = P - unrounded ref per TWSE notes).
                            TPEx: field 每仟股無償配股 / 1000 directly.
  capital_change_ratio      new shares per old share for reductions (每壹仟股換發新股票 / 1000) and par-value
                            changes / splits (停止前收盤價 / 恢復買賣參考價, e.g. 10 -> 2.5 par = 4.0). NaN otherwise.
  action_type               cash | stock | cash+stock | rights | cash+rights | stock+rights |
                            cash+stock+rights | reduction | split
                            ('rights' = 有償現金增資除權: price drops on ex-date but holders receive only a
                            subscription right, no free shares.)
  available_at              Announcement dates are not in these tables. Ex-right/dividend info is public
                            weeks before (board/AGM resolution + 除權息公告), so we use a conservative
                            proxy: (first affected date - 1 trading day) at 18:00+08:00, where the first
                            affected date is the ex-date for dividends and the halt start for
                            reductions/splits (i.e. the last cum trading day 18:00).

CLI: python agent\\data\\fetchers\\corporate_actions.py --start 2024-03-01 --end 2026-10-02
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.data.http import get_bytes, make_session  # noqa: E402
from agent.data.manifest import RAW_DIR, save_raw  # noqa: E402

PARSER_VERSION = "ca-v1"
AVAIL_TIME = "18:00:00"
MIN_INTERVAL = 5.0  # seconds; www.twse.com.tw / www.tpex.org.tw are shared with other backfills

TWSE = "https://www.twse.com.tw/rwd/zh"
URL_TWT49U = TWSE + "/exRight/TWT49U?startDate={s}&endDate={e}&response=json"
URL_TWT49U_DETAIL = TWSE + "/exRight/TWT49UDetail?STK_NO={t}&T1={d}&response=json"
URL_TWTAUU = TWSE + "/reducation/TWTAUU?startDate={s}&endDate={e}&response=json"
URL_TWTAVU_DETAIL = TWSE + "/reducation/TWTAVUDetail?STK_NO={t}&FILE_DATE={d}&response=json"
URL_TWTB8U = TWSE + "/change/TWTB8U?startDate={s}&endDate={e}&response=json"
TPEX = "https://www.tpex.org.tw/www/zh-tw/bulletin"
URL_TPEX_EX = TPEX + "/exDailyQ?startDate={s}&endDate={e}&response=json"
URL_TPEX_REVIVT = TPEX + "/revivt?startDate={s}&endDate={e}&response=json"


# ----------------------------------------------------------------------------- helpers
def roc_to_iso(s: str) -> str | None:
    """'113年07月01日' | '113/07/01' | '1130701' | '20240701' -> '2024-07-01'."""
    t = re.sub(r"[^\d/]", "/", str(s).strip()).strip("/")
    parts = [p for p in t.split("/") if p]
    if len(parts) == 1:
        p = parts[0]
        if len(p) == 8:
            y, m, d = int(p[:4]), int(p[4:6]), int(p[6:])
        elif len(p) == 7:
            y, m, d = int(p[:3]) + 1911, int(p[3:5]), int(p[5:])
        else:
            return None
    elif len(parts) == 3:
        y, m, d = (int(x) for x in parts)
        if y < 1911:
            y += 1911
    else:
        return None
    return date(y, m, d).isoformat()


def num(s) -> float | None:
    """'1,215.00' | '1.2 元／股' | '20 股' | '880.00000000&nbsp股' -> float."""
    if s is None:
        return None
    t = str(s).replace(",", "").replace("&nbsp", " ")
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return float(m.group()) if m else None


def _nz(x) -> float:
    return 0.0 if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def classify(cash: float | None, stock: float | None, rights: bool = False) -> str:
    parts = []
    if _nz(cash) > 0:
        parts.append("cash")
    if _nz(stock) > 0:
        parts.append("stock")
    if rights:
        parts.append("rights")
    return "+".join(parts) if parts else "cash"


def prev_weekday(d: str) -> str:
    x = date.fromisoformat(d) - timedelta(days=1)
    while x.weekday() >= 5:
        x -= timedelta(days=1)
    return x.isoformat()


def prev_trading_day(d: str, calendar: list[str] | None = None) -> str:
    """Last trading day strictly before d. Uses `calendar` (sorted ISO dates) when it covers the
    neighbourhood of d; otherwise falls back to the previous weekday (>= true previous trading day,
    hence never earlier than the truth)."""
    w = prev_weekday(d)
    if calendar:
        import bisect
        i = bisect.bisect_left(calendar, d)
        if i > 0:
            p = calendar[i - 1]
            if (date.fromisoformat(w) - date.fromisoformat(p)).days <= 4:
                return p
    return w


def available_at_before(d: str, calendar: list[str] | None = None) -> str:
    return f"{prev_trading_day(d, calendar)}T{AVAIL_TIME}+08:00"


def _fields_data(j: dict) -> tuple[list[str], list[list]]:
    if "fields" in j and "data" in j:
        return [str(f).strip() for f in j["fields"]], j["data"] or []
    for t in j.get("tables") or []:
        if t.get("fields"):
            return [str(f).strip() for f in t["fields"]], t.get("data") or []
    return [], []


def _col(fields: list[str], *keys: str) -> int:
    for k in keys:
        for i, f in enumerate(fields):
            if k in f:
                return i
    raise KeyError(f"none of {keys} in {fields}")


# ----------------------------------------------------------------------------- TWSE parsers
def parse_twse_twt49u(content: bytes, universe: set[str] | None) -> list[dict]:
    """List rows -> partial events. kind in {'息','權','權息'}; details needed for 權/權息."""
    j = json.loads(content)
    if str(j.get("stat", "")).upper() != "OK":
        return []
    f, data = _fields_data(j)
    i_d, i_t = _col(f, "資料日期"), _col(f, "股票代號")
    i_p, i_r = _col(f, "除權息前收盤價"), _col(f, "除權息參考價")
    i_v, i_k = _col(f, "權值+息值"), _col(f, "權/息")
    out = []
    for r in data:
        t = str(r[i_t]).strip()
        if universe is not None and t not in universe:
            continue
        out.append(dict(ex_date=roc_to_iso(r[i_d]), ticker=t, prev_close=num(r[i_p]),
                        ref_price=num(r[i_r]), value=num(r[i_v]), kind=str(r[i_k]).strip()))
    return out


def parse_twse_twt49u_detail(content: bytes) -> dict | None:
    j = json.loads(content)
    if str(j.get("stat", "")).lower() != "ok" or not j.get("data"):
        return None
    f, data = _fields_data(j)
    r = data[0]
    cash = num(r[_col(f, "現金股利")])
    per1000 = num(r[_col(f, "無償配股")])
    rights_sh = num(r[_col(f, "(有償) 現金增資", "現金增資")])
    sub_ratio = num(r[_col(f, "每千股認購")])
    return dict(cash=cash or 0.0, stock=(per1000 or 0.0) / 1000.0,
                rights=bool(_nz(rights_sh) > 0 or _nz(sub_ratio) > 0))


def event_from_twse(base: dict, detail: dict | None, calendar=None) -> dict:
    k, P, v = base["kind"], base["prev_close"], base["value"]
    src = "twse_twt49u"
    if k == "息":
        cash, stock, rights = v, 0.0, False
    elif detail is not None:
        cash, stock, rights = detail["cash"], detail["stock"], detail["rights"]
        src += "+detail"
    elif k == "權" and P and v is not None and P - v > 0:
        # fallback: pure stock dividend, s = P/(P - 權值) - 1 (cannot tell apart a rights issue)
        cash, stock, rights = 0.0, round(P / (P - v) - 1.0, 8), False
        src += "+derived"
    else:
        cash, stock, rights = float("nan"), float("nan"), False
        src += "+undetermined"
    return dict(ex_date=base["ex_date"], ticker=base["ticker"], cash_dividend=cash,
                stock_dividend_per_share=stock, capital_change_ratio=float("nan"),
                action_type=classify(cash, stock, rights) if not math.isnan(_f(cash)) else "cash+stock",
                source=src, available_at=available_at_before(base["ex_date"], calendar))


def _f(x) -> float:
    return float("nan") if x is None else float(x)


def parse_twse_twtauu(content: bytes, universe: set[str] | None) -> list[dict]:
    j = json.loads(content)
    if str(j.get("stat", "")).upper() != "OK":
        return []
    f, data = _fields_data(j)
    i_d, i_t, i_p, i_r = _col(f, "恢復買賣日期"), _col(f, "股票代號"), _col(f, "停止買賣前收盤"), _col(f, "恢復買賣參考價")
    i_why, i_det = _col(f, "減資原因"), _col(f, "詳細資料")
    out = []
    for r in data:
        t = str(r[i_t]).strip()
        if universe is not None and t not in universe:
            continue
        det = [x.strip() for x in str(r[i_det]).split(",")]
        out.append(dict(ex_date=roc_to_iso(r[i_d]), ticker=t, prev_close=num(r[i_p]), ref_price=num(r[i_r]),
                        reason=str(r[i_why]).strip(), file_date=det[1] if len(det) > 1 else None))
    return out


def parse_twse_twtavu_detail(content: bytes) -> dict | None:
    j = json.loads(content)
    if str(j.get("stat", "")).upper() != "OK" or not j.get("data"):
        return None
    f, data = _fields_data(j)
    r = data[0]
    return dict(halt_start=roc_to_iso(r[_col(f, "停止買賣日期")]),
                new_per1000=num(r[_col(f, "換發新股票")]),
                cash_return=num(r[_col(f, "退還股款")]) or 0.0,
                cash_div=num(r[_col(f, "現金股利")]) or 0.0)


def event_from_reduction(base: dict, detail: dict | None, source: str, calendar=None) -> dict:
    P, ref = base.get("prev_close"), base.get("ref_price")
    if detail and detail.get("new_per1000"):
        ratio = detail["new_per1000"] / 1000.0
        cash = _nz(detail.get("cash_return")) + _nz(detail.get("cash_div"))
        src = source + "+detail"
    elif "彌補虧損" in base.get("reason", "") and P and ref:
        ratio, cash, src = round(P / ref, 6), 0.0, source + "+derived"  # loss offset: ref = P / ratio
    else:
        ratio, cash, src = float("nan"), float("nan"), source + "+undetermined"
    halt = (detail or {}).get("halt_start")
    if halt:
        last_cum = prev_trading_day(halt, calendar)
    elif base.get("file_date"):
        last_cum = roc_to_iso(base["file_date"])  # TWSE FILE_DATE = last trading day before the halt
    else:
        last_cum = prev_trading_day(base["ex_date"], calendar)
    return dict(ex_date=base["ex_date"], ticker=base["ticker"], cash_dividend=cash,
                stock_dividend_per_share=0.0, capital_change_ratio=ratio, action_type="reduction",
                source=src, available_at=f"{last_cum}T{AVAIL_TIME}+08:00")


def parse_twse_twtb8u(content: bytes, universe: set[str] | None, calendar=None) -> list[dict]:
    """Par-value change (e.g. NT$10 -> NT$2.5 = 1:4 split). ratio = new shares per old share."""
    j = json.loads(content)
    if str(j.get("stat", "")).upper() != "OK":
        return []
    f, data = _fields_data(j)
    i_d, i_t, i_p, i_r = _col(f, "恢復買賣日期"), _col(f, "股票代號"), _col(f, "停止買賣前收盤"), _col(f, "恢復買賣參考價")
    i_det = _col(f, "詳細資料")
    out = []
    for r in data:
        t = str(r[i_t]).strip()
        if universe is not None and t not in universe:
            continue
        P, ref = num(r[i_p]), num(r[i_r])
        ratio = round(P / ref, 4) if P and ref else float("nan")
        det = [x.strip() for x in str(r[i_det]).split(",")]
        ex = roc_to_iso(r[i_d])
        # detail = "code,YYYYMMDD(last trading day before halt),YYYYMMDD(resume)"; conservative: that day 18:00
        last_cum = roc_to_iso(det[1]) if len(det) > 1 and det[1] else prev_trading_day(ex, calendar)
        out.append(dict(ex_date=ex, ticker=t, cash_dividend=0.0, stock_dividend_per_share=0.0,
                        capital_change_ratio=ratio, action_type="split", source="twse_twtb8u",
                        available_at=f"{last_cum}T{AVAIL_TIME}+08:00"))
    return out


# ----------------------------------------------------------------------------- TPEx parsers
def parse_tpex_exdailyq(content: bytes, universe: set[str] | None, calendar=None) -> list[dict]:
    j = json.loads(content)
    f, data = _fields_data(j)
    if not f:
        return []
    i_d, i_t = _col(f, "除權息日期"), _col(f, "代號")
    i_cash, i_stk = _col(f, "現金股利"), _col(f, "每仟股無償配股")
    i_rs, i_rr = _col(f, "現金增資股數"), _col(f, "按持股比例仟股認購")
    out = []
    for r in data:
        t = str(r[i_t]).strip()
        if universe is not None and t not in universe:
            continue
        ex = roc_to_iso(r[i_d])
        cash, stock = num(r[i_cash]) or 0.0, (num(r[i_stk]) or 0.0) / 1000.0
        rights = _nz(num(r[i_rs])) > 0 or _nz(num(r[i_rr])) > 0
        out.append(dict(ex_date=ex, ticker=t, cash_dividend=cash, stock_dividend_per_share=round(stock, 8),
                        capital_change_ratio=float("nan"), action_type=classify(cash, stock, rights),
                        source="tpex_exdailyq", available_at=available_at_before(ex, calendar)))
    return out


def parse_tpex_revivt(content: bytes, universe: set[str] | None, calendar=None) -> list[dict]:
    j = json.loads(content)
    f, data = _fields_data(j)
    if not f:
        return []
    i_d, i_t = _col(f, "恢復買賣日期"), _col(f, "股票代號")
    i_p, i_r = _col(f, "最後交易日之收盤"), _col(f, "參考價格")
    i_why, i_det = _col(f, "減資原因"), _col(f, "詳細資料")
    out = []
    for r in data:
        t = str(r[i_t]).strip()
        if universe is not None and t not in universe:
            continue
        txt = re.sub(r"<[^>]+>", "|", str(r[i_det]).replace("&nbsp", " "))
        def grab(label):
            m = re.search(re.escape(label) + r"[:：]?\|+([^|]+)", txt)
            return m.group(1).strip() if m else None
        det = dict(halt_start=roc_to_iso(grab("停止買賣日期")) if grab("停止買賣日期") else None,
                   new_per1000=num(grab("每壹仟股換發新股票")), cash_return=num(grab("每股退還股款")) or 0.0,
                   cash_div=0.0)
        base = dict(ex_date=roc_to_iso(r[i_d]), ticker=t, prev_close=num(r[i_p]), ref_price=num(r[i_r]),
                    reason=str(r[i_why]).strip(), file_date=None)
        out.append(event_from_reduction(base, det, "tpex_revivt", calendar))
    return out


# ----------------------------------------------------------------------------- merge
def merge_events(events: list[dict]) -> list[dict]:
    """Combine events sharing (ex_date, ticker) (e.g. a reduction and a dividend on one day)."""
    by: dict[tuple, dict] = {}
    for e in events:
        k = (e["ex_date"], e["ticker"])
        if k not in by:
            by[k] = dict(e)
            continue
        a = by[k]
        a["cash_dividend"] = _nz(a["cash_dividend"]) + _nz(e["cash_dividend"])
        a["stock_dividend_per_share"] = _nz(a["stock_dividend_per_share"]) + _nz(e["stock_dividend_per_share"])
        r1, r2 = a.get("capital_change_ratio"), e.get("capital_change_ratio")
        a["capital_change_ratio"] = r2 if (r1 is None or math.isnan(_f(r1))) else r1
        a["action_type"] = "+".join(dict.fromkeys(a["action_type"].split("+") + e["action_type"].split("+")))
        a["source"] = a["source"] + ";" + e["source"]
        a["available_at"] = max(a["available_at"], e["available_at"])
    return sorted(by.values(), key=lambda x: (x["ex_date"], x["ticker"]))


# ----------------------------------------------------------------------------- fetch
def _year_chunks(start: str, end: str) -> list[tuple[str, str]]:
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    out = []
    while s <= e:
        ce = min(date(s.year, 12, 31), e)
        out.append((s.isoformat(), ce.isoformat()))
        s = ce + timedelta(days=1)
    return out


class _Fetcher:
    def __init__(self, session, snapshot: str, raw_dir: Path = RAW_DIR, min_interval: float = MIN_INTERVAL):
        self.s, self.snap, self.raw_dir, self.mi = session, snapshot, raw_dir, min_interval
        self.requests = 0

    def get(self, url: str, source: str, filename: str, authority: str, cache: bool = False) -> bytes | None:
        p = self.raw_dir / self.snap / source / filename
        if cache and p.exists():
            return p.read_bytes()
        try:
            b, fetched = get_bytes(self.s, url, min_interval=self.mi, timeout=60, retries=3)
        except Exception as ex:  # noqa: BLE001
            print("  fetch failed:", url, ex, flush=True)
            return None
        self.requests += 1
        ts = fetched.isoformat()
        save_raw(self.snap, source, filename, b, url=url, fetched_at=ts, content_as_of=ts, available_at=ts,
                 authority=authority, parser_version=PARSER_VERSION, raw_dir=self.raw_dir)
        return b


def load_calendar() -> list[str]:
    """Known trading days (read-only) from daily_prices; empty if unavailable."""
    try:
        import pandas as pd
        from agent.data.loaders import HISTORY_DIR
        p = HISTORY_DIR / "daily_prices.parquet"
        if p.exists():
            return sorted(pd.read_parquet(p, columns=["date"])["date"].astype(str).unique().tolist())
    except Exception:  # noqa: BLE001
        pass
    return []


def fetch_corporate_actions(start: str, end: str, twse_uni: set[str], tpex_uni: set[str], *,
                            session=None, raw_dir: Path = RAW_DIR, calendar: list[str] | None = None,
                            min_interval: float = MIN_INTERVAL) -> tuple[list[dict], dict]:
    s = session or make_session()
    fx = _Fetcher(s, end.replace("-", ""), raw_dir, min_interval)
    cal = sorted(set(calendar or []))
    events: list[dict] = []
    stats = {"twse_twt49u": 0, "twse_detail": 0, "twse_reduction": 0, "twse_split": 0,
             "tpex_ex": 0, "tpex_reduction": 0, "failed": []}

    # ---- TWSE ex-right/dividend
    bases = []
    for cs, ce in _year_chunks(start, end):
        a, b = cs.replace("-", ""), ce.replace("-", "")
        c = fx.get(URL_TWT49U.format(s=a, e=b), "twse_twt49u", f"TWT49U_{a}_{b}.json", "twse")
        if c is None:
            stats["failed"].append(f"TWT49U {a}-{b}")
            continue
        bases += parse_twse_twt49u(c, twse_uni)
    # ex-dates are trading days: add them to the calendar
    cal = sorted(set(cal) | {x["ex_date"] for x in bases})
    stats["twse_twt49u"] = len(bases)
    for bse in bases:
        det = None
        if bse["kind"] != "息":
            d8 = bse["ex_date"].replace("-", "")
            c = fx.get(URL_TWT49U_DETAIL.format(t=bse["ticker"], d=d8), "twse_twt49u_detail",
                       f"{bse['ticker']}_{d8}.json", "twse", cache=True)
            det = parse_twse_twt49u_detail(c) if c else None
            if det is None:
                stats["failed"].append(f"TWT49UDetail {bse['ticker']} {d8}")
            else:
                stats["twse_detail"] += 1
        events.append(event_from_twse(bse, det, cal))

    # ---- TWSE capital reduction + par value change
    a, b = start.replace("-", ""), end.replace("-", "")
    c = fx.get(URL_TWTAUU.format(s=a, e=b), "twse_twtauu", f"TWTAUU_{a}_{b}.json", "twse")
    for bse in (parse_twse_twtauu(c, twse_uni) if c else []):
        det = None
        if bse.get("file_date"):
            dc = fx.get(URL_TWTAVU_DETAIL.format(t=bse["ticker"], d=bse["file_date"]), "twse_twtavu_detail",
                        f"{bse['ticker']}_{bse['file_date']}.json", "twse", cache=True)
            det = parse_twse_twtavu_detail(dc) if dc else None
        events.append(event_from_reduction(bse, det, "twse_twtauu", cal))
        stats["twse_reduction"] += 1
    c = fx.get(URL_TWTB8U.format(s=a, e=b), "twse_twtb8u", f"TWTB8U_{a}_{b}.json", "twse")
    sp = parse_twse_twtb8u(c, twse_uni, cal) if c else []
    events += sp
    stats["twse_split"] = len(sp)

    # ---- TPEx
    for cs, ce in _year_chunks(start, end):
        a2, b2 = cs.replace("-", "/"), ce.replace("-", "/")
        c = fx.get(URL_TPEX_EX.format(s=a2, e=b2), "tpex_exdailyq",
                   f"exDailyQ_{cs.replace('-', '')}_{ce.replace('-', '')}.json", "tpex")
        if c is None:
            stats["failed"].append(f"TPEx exDailyQ {cs}-{ce}")
            continue
        ev = parse_tpex_exdailyq(c, tpex_uni, cal)
        events += ev
        stats["tpex_ex"] += len(ev)
    c = fx.get(URL_TPEX_REVIVT.format(s=start.replace("-", "/"), e=end.replace("-", "/")), "tpex_revivt",
               f"revivt_{a}_{b}.json", "tpex")
    rv = parse_tpex_revivt(c, tpex_uni, cal) if c else []
    events += rv
    stats["tpex_reduction"] = len(rv)

    events = [e for e in events if e["ex_date"] and start <= e["ex_date"] <= end]
    stats["requests"] = fx.requests
    return merge_events(events), stats


def main(argv=None):
    from agent.config import load_universe
    from agent.data.loaders import HistoryStore

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--min-interval", type=float, default=MIN_INTERVAL)
    ap.add_argument("--dry-run", action="store_true", help="do not write the history table")
    args = ap.parse_args(argv)
    if args.min_interval < 5:
        ap.error("--min-interval must be >= 5 s for TWSE/TPEx")

    uni = load_universe()
    twse_uni = {t for t, v in uni.items() if v["market"] == "TWSE"}
    tpex_uni = {t for t, v in uni.items() if v["market"] == "TPEx"}
    rows, stats = fetch_corporate_actions(args.start, args.end, twse_uni, tpex_uni,
                                          calendar=load_calendar(), min_interval=args.min_interval)
    print("stats:", json.dumps(stats, ensure_ascii=False))
    if not args.dry_run:
        n = HistoryStore().upsert("corporate_actions", rows)
        print(f"upserted {n} rows into corporate_actions")
    from collections import Counter
    print("action types:", dict(Counter(r["action_type"] for r in rows)))
    print("tickers:", len({r["ticker"] for r in rows}))


if __name__ == "__main__":
    main()
