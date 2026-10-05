"""Real active-ETF holdings from issuer (投信) official websites.

Each active ETF issuer must publish its daily portfolio (每日持股 / PCF). This module calls the
public JSON/XLSX endpoints behind the issuers' own ETF pages (no login, no captcha, no paywall),
keeps every raw response under data/raw/YYYYMMDD/etf_holdings_<etf>/ (+ manifest) and writes
normalized rows to HistoryStore table `etf_holdings` (synthetic=False).

CLI:
    python agent/data/fetchers/etf_holdings.py --all
    python agent/data/fetchers/etf_holdings.py --etf 00981A
    python agent/data/fetchers/etf_holdings.py --all --history 2026-08-31 2026-10-02

Parsers are pure functions `parse_<issuer>(raw: bytes, etf: str) -> Parsed` so they can be
tested offline against saved samples (tests/fixtures/etf_samples/).
"""
from __future__ import annotations

import argparse
import html as _html
import io
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date as _date, datetime, timedelta
from pathlib import Path
from typing import Callable

if __package__ in (None, ""):  # allow `python agent/data/fetchers/etf_holdings.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agent.data.http import TPE, get_bytes, make_session, now_tpe  # noqa: E402

PARSER_VERSION = "etf_holdings-1.0"
AUTHORITY = "fininst"
MIN_INTERVAL = 2.5
STALE_DAYS = 4  # holdings older than this many calendar days vs fetch date -> is_stale (latest mode)
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130 Safari/537.36 (aicup2026-research-agent)")


# --------------------------------------------------------------------------------------------
# Parsed result
# --------------------------------------------------------------------------------------------
@dataclass
class Holding:
    ticker: str
    name: str
    shares: float | None
    weight_pct: float  # percent of NAV (0-100)


@dataclass
class Parsed:
    asof: str | None                      # YYYY-MM-DD holdings date (None = no data for that day)
    holdings: list[Holding] = field(default_factory=list)
    published_at: str | None = None       # ISO +08:00 if the source states it
    nav_total: float | None = None


def _num(x) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", "").replace("%", "")
    s = re.sub(r"^(TWD|NTD|USD)\s*\$?", "", s).strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _ymd(s: str) -> str:
    """'2026/9/1', '20260901', '2026-09-01T00:00:00' -> '2026-09-01'."""
    s = str(s).strip()
    m = re.match(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
    if m:
        return f"{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}"
    m = re.match(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}"
    raise ValueError(f"unparseable date: {s!r}")


def norm_ticker(code: str) -> str:
    """TW codes stay as-is ('2330', '00878'); foreign symbols upper-cased ('LITE US')."""
    c = re.sub(r"\s+", " ", str(code).strip()).upper()
    c = re.sub(r"\.TWO?$", "", c)
    c = re.sub(r"^(\d{4,6}[A-Z]?) (TT|TW)$", r"\1", c)  # Bloomberg-style TW suffix
    return c


# --------------------------------------------------------------------------------------------
# Minimal stdlib XLSX reader (no openpyxl in the venv)
# --------------------------------------------------------------------------------------------
_XNS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def read_xlsx(b: bytes) -> list[list[list[str | None]]]:
    z = zipfile.ZipFile(io.BytesIO(b))
    names = z.namelist()
    ss: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(_XNS + "si"):
            ss.append("".join(t.text or "" for t in si.iter(_XNS + "t")))
    sheets = sorted((n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                    key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    out = []
    for n in sheets:
        rows = []
        for r in ET.fromstring(z.read(n)).iter(_XNS + "row"):
            row: dict[int, str | None] = {}
            for c in r.iter(_XNS + "c"):
                col = re.match(r"[A-Z]+", c.get("r", "A")).group(0)
                idx = 0
                for ch in col:
                    idx = idx * 26 + ord(ch) - 64
                t, v = c.get("t"), c.find(_XNS + "v")
                if t == "s" and v is not None:
                    val = ss[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(_XNS + "t"))
                else:
                    val = v.text if v is not None else None
                row[idx - 1] = val
            rows.append([row.get(i) for i in range(max(row) + 1)] if row else [])
        out.append(rows)
    return out


# --------------------------------------------------------------------------------------------
# Parsers (pure)
# --------------------------------------------------------------------------------------------
def parse_ezmoney(raw: bytes, etf: str) -> Parsed:
    """統一投信 ezmoney ETF/Fund/Info page: Vue `data-content` attribute with asset JSON."""
    t = raw.decode("utf-8", "replace")
    data = None
    for m in re.finditer(r'data-content="([^"]*AssetCode[^"]*)"', t):
        try:
            d = json.loads(_html.unescape(m.group(1)))
        except json.JSONDecodeError:
            continue
        if isinstance(d, list) and d and "Value" in d[0]:
            data = d
            break
    if data is None:
        return Parsed(None)
    hs, asof, pub, nav = [], None, None, None
    for a in data:
        code = str(a.get("AssetCode", "")).upper()
        if code == "NAV":
            nav = _num(a.get("Value"))
        if code != "ST":
            continue
        for d in a.get("Details") or []:
            asof = asof or _ymd(d["TranDate"])
            pub = pub or d.get("EditTime")
            hs.append(Holding(norm_ticker(d["DetailCode"]), d.get("DetailName", ""),
                              _num(d.get("Share")), _num(d.get("NavRate")) or 0.0))
    return Parsed(asof, hs, _iso_tpe(pub) if pub else None, nav)


def parse_nomura(raw: bytes, etf: str) -> Parsed:
    """野村投信 /API/ETFAPI/api/Fund/GetFundAssets JSON."""
    j = json.loads(raw)
    data = (j.get("Entries") or {}).get("Data")
    if not data or not data.get("FundAsset"):
        return Parsed(None)
    fa = data["FundAsset"]
    hs = []
    for tbl in data.get("Table") or []:
        if not str(tbl.get("TableTitle", "")).startswith("股票"):  # 安聯: "股票 (97.01%)"
            continue
        cols = [c["Name"] for c in tbl["Columns"]]
        ic, iname = _col(cols, "代號"), _col(cols, "名稱")
        ish, iw = _col(cols, "股數"), _col(cols, "權重")
        for r in tbl["Rows"]:
            hs.append(Holding(norm_ticker(r[ic]), r[iname], _num(r[ish]), _num(r[iw]) or 0.0))
    return Parsed(_ymd(fa["NavDate"]), hs, None, _num(fa.get("Aum")))


def parse_capital(raw: bytes, etf: str) -> Parsed:
    """群益投信 /CFWeb/api/etf/buyback JSON. pcf.date2 = NAV/holdings date, date1 = PCF trade date."""
    j = json.loads(raw)
    d = j.get("data") or {}
    pcf = d.get("pcf")
    if not pcf or not d.get("stocks"):
        return Parsed(None)
    hs = [Holding(norm_ticker(s["stocNo"]), s.get("stocName", ""), _num(s.get("share")),
                  _num(s.get("weight")) or 0.0) for s in d["stocks"]]
    return Parsed(_ymd(pcf["date2"]), hs, None, _num(pcf.get("nav")))


def parse_fhtrust(raw: bytes, etf: str) -> Parsed:
    """復華投信 /api/assetsExcel/<ETFid>/<yyyymmdd> XLSX."""
    sheets = read_xlsx(raw)
    if not sheets:
        return Parsed(None)
    rows = sheets[0]
    asof, hs, nav, hdr = None, [], None, None
    for i, r in enumerate(rows):
        cells = [c for c in r if c is not None]
        if not cells:
            continue
        first = str(cells[0])
        m = re.search(r"日期[:：]\s*(\d{4}/\d{1,2}/\d{1,2})", first)
        if m:
            asof = _ymd(m.group(1))
        if first.startswith("基金資產淨值") and i + 1 < len(rows) and rows[i + 1]:
            nav = _num(rows[i + 1][0])
        if "證券代號" in [str(c) for c in r]:
            hdr = [str(c) if c is not None else "" for c in r]
            continue
        if hdr and r and r[0] and len(r) >= len(hdr) - 1:
            code = str(r[0]).strip()
            if not re.match(r"^[0-9A-Z]{4,6}$|^[A-Z0-9.]+ [A-Z]{2}$", code):
                if hs:  # end of stock block
                    hdr = None
                continue
            hs.append(Holding(norm_ticker(code), str(r[_col(hdr, "名稱")] or ""),
                              _num(r[_col(hdr, "股數")]), _num(r[_col(hdr, "權重")]) or 0.0))
    if not hs:
        return Parsed(None)
    return Parsed(asof, hs, None, nav)


def parse_yuanta(raw: bytes, etf: str) -> Parsed:
    """元大投信 etfapi bridge FuncId=PCF/Daily JSON. PCF.trandate = holdings date."""
    j = json.loads(raw)
    if "Data" in j and "PCF" not in j:
        j = j["Data"] or {}
    pcf = j.get("PCF")
    fw = (j.get("FundWeights") or {}).get("StockWeights") or []
    if not pcf or not fw:
        return Parsed(None)
    hs = [Holding(norm_ticker(s["code"]), s.get("name", ""), _num(s.get("qty")),
                  _num(s.get("weights")) or 0.0) for s in fw]
    pub = pcf.get("upddate")
    return Parsed(_ymd(pcf["trandate"]), hs, _iso_tpe(pub) if pub else None, _num(pcf.get("totalav")))


def parse_cathay(raw: bytes, etf: str, asof: str | None = None) -> Parsed:
    """國泰投信 cwapi /api/ETF/GetETFDetailStockList JSON (date = the SearchDate requested).

    The fetcher wraps the response as {"SearchDate": ..., "stock": <resp>} so the raw snapshot
    is self-describing."""
    j = json.loads(raw)
    if "stock" in j:
        asof = asof or j.get("SearchDate")
        j = j["stock"]
    res = j.get("result")
    if not j.get("success") or not res or not asof:
        return Parsed(None)
    hs = [Holding(norm_ticker(s["stockCode"]), s.get("stockName", ""), _num(s.get("volumn")),
                  _num(s.get("weights")) or 0.0) for s in res]
    return Parsed(_ymd(asof), hs)


def parse_ab(raw: bytes, etf: str) -> Parsed:
    """聯博投信 webapi.alliancebernstein.com .../holdings JSON (equity section only)."""
    j = json.loads(raw)
    asof, hs = None, []
    for g in j.get("domesticHoldings") or []:
        if g.get("holdingCategory") != "holdings-section-equity":
            continue
        if g.get("asOfDate") and not asof:
            mm, dd, yy = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", g["asOfDate"]).groups()
            asof = f"{yy}-{int(mm):02d}-{int(dd):02d}"
        for h in g.get("holdings") or []:
            hs.append(Holding(norm_ticker(h["holdingCode"]), h.get("holding", ""),
                              _num(h.get("holdingShares")), _num(h.get("holdingPerc")) or 0.0))
    return Parsed(asof, hs) if (asof and hs) else Parsed(None)


def parse_ctbc(raw: bytes, etf: str) -> Parsed:
    """中信投信 /API/etf/ETFHoldingWeight JSON; FundAssets[0]['資料日期'] = holdings date."""
    j = json.loads(raw)
    d = j.get("Data") or {}
    fa = d.get("FundAssets") or []
    asof = fa[0].get("資料日期") if fa else None
    hs = []
    for g in d.get("FundAssetsDetail") or []:
        if str(g.get("Code", "")).upper() != "STOCK":
            continue
        for r in g.get("Data") or []:
            hs.append(Holding(norm_ticker(r["code_"]), r.get("name_", ""), _num(r.get("qty_")),
                              _num(r.get("weights_")) or 0.0))
    return Parsed(_ymd(asof), hs) if (asof and hs) else Parsed(None)


# ---- HTML-table issuers (富邦 / 凱基 / 永豐 / 台新) -------------------------------------------
_TAG = re.compile(r"<[^>]+>")
_CODE_RE = re.compile(r"^[0-9A-Z]{4,6}$|^[0-9A-Z./]+ [A-Z]{2}$")


def _cells(tr: str) -> list[str]:
    return [re.sub(r"\s+", " ", _html.unescape(_TAG.sub("", c))).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)]


def html_holdings_table(t: str, start: int = 0) -> list[Holding]:
    """First <table> (from `start`) whose header has a code column and a weight column."""
    for m in re.finditer(r"<table\b.*?</table>", t[start:], flags=re.S | re.I):
        rows = [_cells(tr) for tr in re.findall(r"<tr\b.*?</tr>", m.group(0), flags=re.S | re.I)]
        hdr_i = next((i for i, r in enumerate(rows)
                      if any(re.search("代號|代碼", c) for c in r) and any("權重" in c for c in r)), None)
        if hdr_i is None:
            continue
        hdr = rows[hdr_i]
        ic = next(i for i, c in enumerate(hdr) if re.search("代號|代碼", c))
        iw = next(i for i, c in enumerate(hdr) if "權重" in c)
        inm = next((i for i, c in enumerate(hdr) if "名稱" in c), ic + 1)
        ish = next((i for i, c in enumerate(hdr) if "股數" in c), None)
        out = []
        for r in rows[hdr_i + 1:]:
            if len(r) < len(hdr) or not _CODE_RE.match(r[ic].strip().upper()):
                continue
            out.append(Holding(norm_ticker(r[ic]), r[inm], _num(r[ish]) if ish is not None else None,
                               _num(r[iw]) or 0.0))
        if out:
            return out
    return []


def _html_parsed(raw: bytes, date_re: str, start_marker: str | None = None) -> Parsed:
    t = _html.unescape(raw.decode("utf-8", "replace"))
    m = re.search(date_re, t)
    st = max(t.find(start_marker), 0) if start_marker else 0
    hs = html_holdings_table(t, st)
    return Parsed(_ymd(m.group(1)), hs) if (m and hs) else Parsed(None)


def parse_fubon(raw: bytes, etf: str) -> Parsed:
    """富邦投信 websys.fsit.com.tw/FubonETF/Trade/Assets.aspx; '資料日期：' = holdings date."""
    return _html_parsed(raw, r"資料日期[:：]\s*(\d{4}/\d{1,2}/\d{1,2})", "pnlEtf")


def parse_kgi(raw: bytes, etf: str) -> Parsed:
    """凱基投信 POST /Fund/RedemptionVC fragment; holdings date = '(YYYY/MM/DD)每受益權單位淨資產價值'."""
    return _html_parsed(raw, r"\((\d{4}/\d{1,2}/\d{1,2})\)\s*每受益權單位淨資產價值")


def parse_sinopac(raw: bytes, etf: str) -> Parsed:
    """永豐投信 /SinopacEtfs/Etfs/Pcf/<etf>; '資料日期：' = holdings date (first = PC table)."""
    return _html_parsed(raw, r"資料日期[:：]\s*(\d{4}/\d{1,2}/\d{1,2})")


def parse_tsit(raw: bytes, etf: str) -> Parsed:
    """台新投信 /ETF/Home/ETFSeriesDetail/<etf>; hidden input NAV_DATE = holdings date."""
    return _html_parsed(raw, r'NAV_DATE"[^>]*value="(\d{4}/\d{1,2}/\d{1,2})', "paneFive1")


def parse_mega(raw: bytes, etf: str) -> Parsed:
    """兆豐投信 trade_pcf.aspx postback; '<YYYY/MM/DD> 每基數申購總價金差異額' = holdings date."""
    return _html_parsed(raw, r"(\d{4}/\d{1,2}/\d{1,2})\s*每基數申購總價金差異額", "divStockCash")


def parse_fsitc(raw: bytes, etf: str) -> Parsed:
    """第一金投信 WebAPI.aspx/Get_hd: {"d": "<json list>"}; group "1" = stocks, sdate = holdings date."""
    rows = json.loads(json.loads(raw)["d"] or "[]")
    st = [r for r in rows if str(r.get("group")) == "1" and r.get("A")]
    if not st:
        return Parsed(None)
    hs = [Holding(norm_ticker(r["A"]), r.get("B", ""), _num(r.get("D")), _num(r.get("C")) or 0.0) for r in st]
    return Parsed(_ymd(st[0]["sdate"]), hs)


def parse_jpm(raw: bytes, etf: str) -> Parsed:
    """摩根投信: holding_pcf XLSX (sheet 1 '基金資產 - 股票 (YYYY-MM-DD)') or product-data JSON."""
    if raw[:2] == b"PK":
        sheets = read_xlsx(raw)
        if not sheets or not sheets[0]:
            return Parsed(None)
        rows = sheets[0]
        m = re.search(r"\((\d{4}-\d{2}-\d{2})\)", str(rows[0][0] if rows[0] else ""))
        hdr_i = next((i for i, r in enumerate(rows) if r and "股票代碼" in [str(c) for c in r]), None)
        if not m or hdr_i is None:
            return Parsed(None)
        hdr = [str(c) for c in rows[hdr_i]]
        ic, inm, ish, iw = _col(hdr, "代碼"), _col(hdr, "名稱"), _col(hdr, "股數"), _col(hdr, "權重")
        hs = [Holding(norm_ticker(r[ic]), str(r[inm] or ""), _num(r[ish]), _num(r[iw]) or 0.0)
              for r in rows[hdr_i + 1:] if r and len(r) > iw and r[ic] and _CODE_RE.match(str(r[ic]).strip().upper())]
        return Parsed(m.group(1), hs) if hs else Parsed(None)
    j = json.loads(raw)
    eq = (((j.get("fundData") or {}).get("holdings") or {}).get("pcfEquityHoldings") or {})
    data = eq.get("data") or []
    if not data or not eq.get("effectiveDate"):
        return Parsed(None)
    hs = [Holding(norm_ticker(r["securityTicker"]), r.get("securityDescription", ""), _num(r.get("shares")),
                  _num(r.get("marketValuePercent")) or 0.0) for r in data if r.get("securityTicker")]
    return Parsed(_ymd(eq["effectiveDate"]), hs)


def _col(cols: list[str], key: str) -> int:
    for i, c in enumerate(cols):
        if key in str(c):
            return i
    raise KeyError(f"column containing {key!r} not in {cols}")


def _iso_tpe(s: str) -> str:
    s = str(s).strip().replace("T", " ")
    s = re.sub(r"\.\d+", "", s)
    s = re.sub(r"([+-]\d{2}:\d{2}|Z)$", "", s).strip()
    dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S") if len(s) >= 19 else \
        datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=TPE).isoformat()


# --------------------------------------------------------------------------------------------
# Fetchers: (session, etf, fund_id, query_date|None) -> (raw bytes, url, ext)
# query_date is YYYY-MM-DD; None = latest.
# --------------------------------------------------------------------------------------------
def _post_json(session, url: str, body: dict, headers: dict | None = None, form: bool = False) -> bytes:
    """POST with the same per-host throttle as get_bytes."""
    import time
    from agent.data import http as H
    host = url.split("/")[2]
    last = None
    for attempt in range(3):
        wait = H._last_call.get(host, 0) + MIN_INTERVAL - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            if form:
                r = session.post(url, data=body, headers=headers or {}, timeout=30)
            else:
                r = session.post(url, json=body, headers=headers or {}, timeout=30)
            H._last_call[host] = time.time()
            r.raise_for_status()
            return r.content
        except Exception as e:  # noqa: BLE001
            H._last_call[host] = time.time()
            last = e
            time.sleep(MIN_INTERVAL * (attempt + 2))
    raise RuntimeError(f"POST failed: {url}: {last}")


def _get(session, url: str, params=None, headers: dict | None = None) -> bytes:
    saved = dict(session.headers)
    try:
        if headers:
            session.headers.update(headers)
        b, _ = get_bytes(session, url, params=params, min_interval=MIN_INTERVAL)
    finally:  # per-issuer Referer/Origin must not leak to other hosts
        session.headers.clear()
        session.headers.update(saved)
    return b


def fetch_ezmoney(session, etf, fund_id, qdate):
    if qdate is not None:
        raise NotImplementedError("ezmoney Info page only shows the latest portfolio")
    url = f"https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode={fund_id}"
    return _get(session, url), url, "html"


def fetch_nomura(session, etf, fund_id, qdate):
    url = "https://www.nomurafunds.com.tw/API/ETFAPI/api/Fund/GetFundAssets"
    d = qdate or now_tpe().date().isoformat()
    def has(b):
        return bool(((json.loads(b).get("Entries") or {}).get("Data") or {}).get("FundAsset"))
    b = _post_json(session, url, {"FundID": fund_id, "SearchDate": d})
    if qdate is None and not has(b):
        # today not yet published / weekend -> walk back up to 7 days
        for k in range(1, 8):
            d = (now_tpe().date() - timedelta(days=k)).isoformat()
            b = _post_json(session, url, {"FundID": fund_id, "SearchDate": d})
            if has(b):
                break
    return b, f"{url}#FundID={fund_id}&SearchDate={d}", "json"


def fetch_capital(session, etf, fund_id, qdate):
    url = "https://www.capitalfund.com.tw/CFWeb/api/etf/buyback"
    body = {"fundId": fund_id, "date": qdate}
    hdr = {"Referer": f"https://www.capitalfund.com.tw/etf/product/detail/{fund_id}/portfolio"}
    return _post_json(session, url, body, hdr), f"{url}#fundId={fund_id}&date={qdate or ''}", "json"


def fetch_fhtrust(session, etf, fund_id, qdate):
    if qdate is None:
        page = f"https://www.fhtrust.com.tw/ETF/etf_detail/{fund_id}"
        t = _get(session, page).decode("utf-8", "replace")
        m = re.search(rf"/api/assetsExcel/{fund_id}/(\d{{8}})", t)
        ymd = m.group(1) if m else now_tpe().strftime("%Y%m%d")
    else:
        ymd = qdate.replace("-", "")
    url = f"https://www.fhtrust.com.tw/api/assetsExcel/{fund_id}/{ymd}"
    return _get(session, url), url, "xlsx"


YUANTA_BRIDGE = "https://etfapi.yuantaetfs.com/ectranslation/api/bridge"


def fetch_yuanta(session, etf, fund_id, qdate):
    p = dict(APIType="ETFAPI", CompanyName="YUANTAFUNDS", PageName=f"/product/detail/{etf}/ratio",
             DeviceId="null", FuncId="PCF/Daily", AppName="ETF", Device="3", Platform="ETF", ticker=etf)
    if qdate:
        p["date"] = qdate.replace("-", "")  # = announcement (PCF) date
    b = _get(session, YUANTA_BRIDGE, params=p)
    q = "&".join(f"{k}={v}" for k, v in p.items())
    return b, f"{YUANTA_BRIDGE}?{q}", "json"


CATHAY_API = "https://cwapi.cathaysite.com.tw/api/ETF/"


def fetch_cathay(session, etf, fund_id, qdate):
    hdr = {"Referer": "https://www.cathaysite.com.tw/", "Origin": "https://www.cathaysite.com.tw"}
    if qdate is None:
        a = json.loads(_get(session, CATHAY_API + "GetETFAssets", {"FundCode": fund_id, "status": 1}, hdr))
        qdate = _ymd(a["result"]["preDate"])
    sd = qdate.replace("-", "/")
    params = {"FundCode": fund_id, "SearchDate": sd, "status": 1}
    b = _get(session, CATHAY_API + "GetETFDetailStockList", params, hdr)
    wrapped = json.dumps({"SearchDate": qdate, "stock": json.loads(b)}, ensure_ascii=False).encode()
    url = f"{CATHAY_API}GetETFDetailStockList?FundCode={fund_id}&SearchDate={sd}&status=1"
    return wrapped, url, "json"


def fetch_ab(session, etf, fund_id, qdate):
    url = f"https://webapi.alliancebernstein.com/v2/funds/tw/zh-tw/investor/{fund_id}/holdings"
    b = _get(session, url, params={"date": qdate} if qdate else None)
    return b, url + (f"?date={qdate}" if qdate else ""), "json"


def fetch_fubon(session, etf, fund_id, qdate):
    url = f"https://websys.fsit.com.tw/FubonETF/Trade/Assets.aspx?stkId={fund_id}&lan=TW"
    if qdate:
        url += f"&ddate={qdate.replace('-', '/')}"
    return _get(session, url), url, "html"


def fetch_kgi(session, etf, fund_id, qdate):
    url = "https://www.kgifund.com.tw/Fund/RedemptionVC"
    body = {"fundID": fund_id}
    if qdate:
        body["queryDate"] = qdate.replace("-", "/")  # announcement date; holdings = previous day
    b = _post_json(session, url, body, {"Referer": "https://www.kgifund.com.tw/"}, form=True)
    return b, f"{url}#fundID={fund_id}&queryDate={body.get('queryDate', '')}", "html"


def fetch_sinopac(session, etf, fund_id, qdate):
    url = f"https://sitc.sinopac.com/SinopacEtfs/Etfs/Pcf/{fund_id}"
    if qdate is None:
        return _get(session, url), url, "html"
    body = {"fundId": fund_id, "hDate": qdate, "op": "1"}  # hDate = announcement date
    b = _post_json(session, url, body, {"Referer": url}, form=True)
    return b, f"{url}#hDate={qdate}&op=1", "html"


def fetch_tsit(session, etf, fund_id, qdate):
    if qdate is not None:
        raise NotImplementedError("tsit page shows the latest portfolio only")
    url = f"https://www.tsit.com.tw/ETF/Home/ETFSeriesDetail/{fund_id}"
    return _get(session, url), url, "html"


CTBC_API = "https://www.ctbcinvestments.com.tw/API/"
_CTBC_HDR = {"Origin": "https://www.ctbcinvestments.com", "Referer": "https://www.ctbcinvestments.com/"}


def fetch_ctbc(session, etf, fund_id, qdate):
    """Anonymous page token (what the public site requests on load) -> ETFHoldingWeight.
    StartDate returns the latest holdings on/before that date."""
    sd = (qdate or now_tpe().date().isoformat()).replace("-", "/")
    for _ in range(3):  # tokens sometimes come back already invalid -> refresh and retry
        tok_b = _post_json(session, CTBC_API + "home/AuthToken?token=www.ctbcinvestments.com",
                           {"token": "www.ctbcinvestments.com"}, _CTBC_HDR)
        tok = json.loads(tok_b)["Data"]["token"]
        b = _post_json(session, f"{CTBC_API}etf/ETFHoldingWeight?token={tok}",
                       {"token": tok, "FID": fund_id, "StartDate": sd}, _CTBC_HDR)
        if json.loads(b).get("ResultCode") == 0:
            break
    else:   # Round 07: daytime runs saw every attempt fail; surface the API code instead of "empty for latest"
        j = json.loads(b)
        raise RuntimeError(f"CTBC ETFHoldingWeight ResultCode={j.get('ResultCode')} "
                           f"{str(j.get('Message') or j.get('ResultMessage') or '')[:80]}")
    return b, f"{CTBC_API}etf/ETFHoldingWeight#FID={fund_id}&StartDate={sd}", "json"


def fetch_fsitc(session, etf, fund_id, qdate):
    url = "https://www.fsitc.com.tw/WebAPI.aspx/Get_hd"
    d = qdate.replace("-", "/") if qdate else ""  # = PCF date; holdings (sdate) = previous trading day
    b = _post_json(session, url, {"pStrFundID": fund_id, "pStrDate": d})
    return b, f"{url}#pStrFundID={fund_id}&pStrDate={d}", "json"


MEGA_PCF = "https://www.megafunds.com.tw/MEGA/etf/trade_pcf.aspx"


def fetch_mega(session, etf, fund_id, qdate):
    """ASP.NET postback: GET the form (hidden __VIEWSTATE etc.), then POST fund_id + qdt."""
    t = _get(session, MEGA_PCF).decode("utf-8", "replace")
    form = {m.group(1): _html.unescape(m.group(2)) for m in re.finditer(
        r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', t)}
    qd = (qdate or now_tpe().date().isoformat()).replace("-", "/")  # qdt = PCF date
    form.update({"ctl00$ContentPlaceHolder1$category_id": "", "ctl00$ContentPlaceHolder1$fund_id": fund_id,
                 "ctl00$ContentPlaceHolder1$qdt": qd, "ctl00$ContentPlaceHolder1$button2": "查 詢"})
    b = _post_json(session, MEGA_PCF, form, {"Referer": MEGA_PCF}, form=True)
    return b, f"{MEGA_PCF}#fund_id={fund_id}&qdt={qd}", "html"


JPM_HANDLER = "https://am.jpmorgan.com/FundsMarketingHandler/"


def fetch_jpm(session, etf, fund_id, qdate):
    """Latest: product-data JSON; history: holding_pcf Excel with date= (holdings date)."""
    if qdate is None:
        url = (f"{JPM_HANDLER}product-data?cusip={fund_id}&country=tw&role=twetf&language=zh"
               f"&userLoggedIn=false")
        return _get(session, url), url, "json"
    url = (f"{JPM_HANDLER}excel?type=holding_pcf&cusip={fund_id}&country=tw&role=twetf"
           f"&locale=zh-TW&date={qdate}")
    return _get(session, url), url, "xlsx"


ALLIANZ_API = "https://etf.allianzgi.com.tw/webapi/api/"


def fetch_allianz(session, etf, fund_id, qdate):
    if qdate is not None:
        raise NotImplementedError("allianz GetFundAssets returns the latest day only")
    hdr = {"Referer": "https://etf.allianzgi.com.tw/", "Origin": "https://etf.allianzgi.com.tw"}
    _get(session, ALLIANZ_API + "AntiForgery/GetAntiForgeryToken", headers=hdr)  # sets XSRF cookie
    xsrf = session.cookies.get("X-XSRF-TOKEN") or session.cookies.get("XSRF-TOKEN") or ""
    b = _post_json(session, ALLIANZ_API + "Fund/GetFundAssets", {"FundID": fund_id},
                   dict(hdr, **{"X-XSRF-TOKEN": xsrf}))
    return b, f"{ALLIANZ_API}Fund/GetFundAssets#FundID={fund_id}", "json"


# --------------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------------
@dataclass
class Source:
    issuer: str
    kind: str                       # key in ISSUERS
    fund_id: str | None
    foreign: bool = False
    note: str = ""


ISSUERS: dict[str, dict] = {
    # kind: (fetch, parse, history_supported, url pattern for the report)
    "ezmoney": dict(fetch=fetch_ezmoney, parse=parse_ezmoney, history=False,
                    pattern="GET www.ezmoney.com.tw/ETF/Fund/Info?fundCode=<id> (embedded JSON)"),
    "nomura": dict(fetch=fetch_nomura, parse=parse_nomura, history=True,
                   pattern="POST www.nomurafunds.com.tw/API/ETFAPI/api/Fund/GetFundAssets {FundID,SearchDate}"),
    "capital": dict(fetch=fetch_capital, parse=parse_capital, history=True,
                    pattern="POST www.capitalfund.com.tw/CFWeb/api/etf/buyback {fundId,date}"),
    "fhtrust": dict(fetch=fetch_fhtrust, parse=parse_fhtrust, history=True,
                    pattern="GET www.fhtrust.com.tw/api/assetsExcel/<id>/<yyyymmdd> (xlsx)"),
    "yuanta": dict(fetch=fetch_yuanta, parse=parse_yuanta, history=True,
                   pattern="GET etfapi.yuantaetfs.com/ectranslation/api/bridge FuncId=PCF/Daily&ticker&date"),
    "cathay": dict(fetch=fetch_cathay, parse=parse_cathay, history=True,
                   pattern="GET cwapi.cathaysite.com.tw/api/ETF/GetETFDetailStockList?FundCode&SearchDate"),
    "ab": dict(fetch=fetch_ab, parse=parse_ab, history=True,
               pattern="GET webapi.alliancebernstein.com/v2/funds/tw/zh-tw/investor/<ISIN>/holdings?date="),
    "fubon": dict(fetch=fetch_fubon, parse=parse_fubon, history=True,
                  pattern="GET websys.fsit.com.tw/FubonETF/Trade/Assets.aspx?stkId&ddate (HTML)"),
    "kgi": dict(fetch=fetch_kgi, parse=parse_kgi, history=True,
                pattern="POST www.kgifund.com.tw/Fund/RedemptionVC fundID&queryDate (HTML)"),
    "sinopac": dict(fetch=fetch_sinopac, parse=parse_sinopac, history=True,
                    pattern="POST sitc.sinopac.com/SinopacEtfs/Etfs/Pcf/<etf> hDate&op=1 (HTML)"),
    "ctbc": dict(fetch=fetch_ctbc, parse=parse_ctbc, history=True,
                 pattern="POST www.ctbcinvestments.com.tw/API/etf/ETFHoldingWeight {FID,StartDate} (+anon token)"),
    "allianz": dict(fetch=fetch_allianz, parse=parse_nomura, history=False,
                    pattern="POST etf.allianzgi.com.tw/webapi/api/Fund/GetFundAssets {FundID} (+XSRF cookie)"),
    "fsitc": dict(fetch=fetch_fsitc, parse=parse_fsitc, history=True,
                  pattern="POST www.fsitc.com.tw/WebAPI.aspx/Get_hd {pStrFundID,pStrDate}"),
    "mega": dict(fetch=fetch_mega, parse=parse_mega, history=True,
                 pattern="POST www.megafunds.com.tw/MEGA/etf/trade_pcf.aspx (ASP.NET form, fund_id&qdt)"),
    "jpm": dict(fetch=fetch_jpm, parse=parse_jpm, history=True,
                pattern="GET am.jpmorgan.com/FundsMarketingHandler/product-data | excel?type=holding_pcf&date="),
    "tsit": dict(fetch=fetch_tsit, parse=parse_tsit, history=False,
                 pattern="GET www.tsit.com.tw/ETF/Home/ETFSeriesDetail/<etf> (HTML)"),
}

REGISTRY: dict[str, Source] = {
    "00980A": Source("野村", "nomura", "00980A"),
    "00985A": Source("野村", "nomura", "00985A"),
    "00999A": Source("野村", "nomura", "00999A"),
    "00982A": Source("群益", "capital", "399"),
    "00992A": Source("群益", "capital", "500"),
    "00997A": Source("群益", "capital", "502", foreign=True),
    "00981A": Source("統一", "ezmoney", "49YTW"),
    "00988A": Source("統一", "ezmoney", "61YTW", foreign=True),
    "00403A": Source("統一", "ezmoney", "63YTW"),
    "00991A": Source("復華", "fhtrust", "ETF23"),
    "00409A": Source("復華", "fhtrust", "ETF26", foreign=True),
    "00990A": Source("元大", "yuanta", "1254", note="global AI (TW + US stocks); foreign legs lag 1 day"),
    "00400A": Source("國泰", "cathay", "EA"),
    # --- second batch ---
    "00983A": Source("中信", "ctbc", "E0034", foreign=True),
    "00995A": Source("中信", "ctbc", "E0036"),
    "00406A": Source("中信", "ctbc", "E0038"),
    "00984A": Source("安聯", "allianz", "E0001"),
    "00993A": Source("安聯", "allianz", "E0002"),
    "00402A": Source("安聯", "allianz", "E0003", foreign=True),
    "00986A": Source("台新", "tsit", "00986A", foreign=True, note="actually global (~71% US)"),
    "00987A": Source("台新", "tsit", "00987A"),
    "00989A": Source("摩根", "jpm", "TW00000989A5", foreign=True),
    "00401A": Source("摩根", "jpm", "TW00000401A1", note="covered-call; option legs excluded"),
    "00994A": Source("第一金", "fsitc", "182"),
    "00408A": Source("第一金", "fsitc", "183"),
    "00996A": Source("兆豐", "mega", "23"),
    "00404A": Source("聯博", "ab", "TW00000404A5"),
    "00405A": Source("富邦", "fubon", "00405A"),
    "00407A": Source("凱基", "kgi", "J024"),
    "00410A": Source("永豐", "sinopac", "00410A"),
}


# --------------------------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------------------------
def to_rows(p: Parsed, etf: str, *, source_url: str, fetched_at: str, latest_mode: bool,
            authority: str = AUTHORITY) -> list[dict]:
    """Parsed -> etf_holdings rows (weight fraction, rank by weight, PIT available_at)."""
    if not p.asof or not p.holdings:
        return []
    agg: dict[str, Holding] = {}
    for h in p.holdings:
        if not h.ticker:
            continue
        if h.ticker in agg:  # same security listed twice (e.g. split lots) -> merge
            o = agg[h.ticker]
            o.weight_pct += h.weight_pct
            o.shares = (o.shares or 0) + (h.shares or 0)
        else:
            agg[h.ticker] = Holding(h.ticker, h.name, h.shares, h.weight_pct)
    hs = sorted(agg.values(), key=lambda h: (-h.weight_pct, h.ticker))
    eod = f"{p.asof}T22:00:00+08:00"
    available_at = max(eod, p.published_at) if p.published_at else eod
    stale = False
    if latest_mode:
        fd = datetime.fromisoformat(fetched_at).date()
        stale = (fd - _date.fromisoformat(p.asof)).days > STALE_DAYS
    return [dict(date=p.asof, etf=etf, ticker=h.ticker, weight=round(h.weight_pct / 100.0, 8),
                 rank=i + 1, shares=h.shares, source_url=source_url,
                 published_at=p.published_at or "", fetched_at=fetched_at, authority=authority,
                 is_stale=stale, available_at=available_at, synthetic=False)
            for i, h in enumerate(hs)]


# --------------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------------
@dataclass
class Result:
    etf: str
    issuer: str
    source: str
    status: str
    asof: str | None = None
    n: int = 0
    top10: float = 0.0
    rows: list[dict] = field(default_factory=list)
    reason: str = ""


def _session():
    s = make_session()
    s.headers["User-Agent"] = BROWSER_UA
    s.headers["Accept"] = "application/json, text/plain, */*"
    return s


def fetch_one(session, etf: str, qdate: str | None = None, *, save: bool = True) -> Result:
    src = REGISTRY.get(etf)
    if src is None:
        return Result(etf, "?", "", "unknown_etf")
    if not src.kind:
        return Result(etf, src.issuer, "", "unsupported", reason=src.note)
    spec = ISSUERS[src.kind]
    if qdate is not None and not spec["history"]:
        return Result(etf, src.issuer, src.kind, "no_history", reason="issuer page shows latest only")
    try:
        raw, url, ext = spec["fetch"](session, etf, src.fund_id, qdate)
        fetched_at = now_tpe().isoformat()
        p = spec["parse"](raw, etf)
    except Exception as e:  # noqa: BLE001
        return Result(etf, src.issuer, src.kind, "error", reason=f"{type(e).__name__}: {e}"[:200])
    if not p.asof or not p.holdings:
        return Result(etf, src.issuer, src.kind, "no_data", reason=f"empty for {qdate or 'latest'}")
    rows = to_rows(p, etf, source_url=url, fetched_at=fetched_at, latest_mode=qdate is None)
    if save:
        from agent.data.manifest import save_raw
        save_raw(p.asof.replace("-", ""), f"etf_holdings_{etf}",
                 f"{src.kind}_{etf}_{p.asof.replace('-', '')}.{ext}", raw, url=url,
                 fetched_at=fetched_at, content_as_of=f"{p.asof}T13:30:00+08:00",
                 available_at=rows[0]["available_at"], authority=AUTHORITY,
                 parser_version=PARSER_VERSION, published_at=p.published_at)
    top10 = sum(r["weight"] for r in rows[:10])
    status = "stale" if rows[0]["is_stale"] else "ok"
    return Result(etf, src.issuer, src.kind, status, p.asof, len(rows), top10, rows)


def trading_days(start: str, end: str) -> list[str]:
    """Trading days from the local price history if available, else weekdays."""
    try:
        from agent.data.loaders import HistoryStore
        ds = [d for d in HistoryStore().dates("daily_prices") if start <= d <= end]
        if ds and ds[-1] >= end[:7]:
            return ds
    except Exception:  # noqa: BLE001
        pass
    d0, d1 = _date.fromisoformat(start), _date.fromisoformat(end)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)
            if (d0 + timedelta(days=i)).weekday() < 5]


LAGGED_QUERY = {"capital", "yuanta", "kgi", "sinopac", "fsitc", "mega"}  # query = PCF date


def fetch_history(session, etf: str, start: str, end: str, *, save: bool = True) -> list[Result]:
    """Query each trading day in [start, end]; keep one result per distinct holdings date.

    For 群益/元大 the query date is the PCF/announcement date and the returned holdings date is the
    previous trading day, so we also query one extra day past `end`."""
    src = REGISTRY[etf]
    if not src.kind or not ISSUERS[src.kind]["history"]:
        return []
    days = trading_days(start, end)
    if src.kind in LAGGED_QUERY:  # query date = PCF/announcement date (holdings lag 1-2 days)
        extra, added = _date.fromisoformat(end), 0
        while added < 2:
            extra += timedelta(days=1)
            if extra.weekday() < 5 and extra.isoformat() <= now_tpe().date().isoformat():
                days.append(extra.isoformat())
                added += 1
            if extra.isoformat() > now_tpe().date().isoformat():
                break
    seen, out = set(), []
    for d in days:
        r = fetch_one(session, etf, d, save=save)
        if r.asof and (r.asof in seen or not (start <= r.asof <= end)):
            continue
        if r.asof:
            seen.add(r.asof)
        out.append(r)
    return out


def store_rows(rows: list[dict]) -> int:
    from agent.data.loaders import HistoryStore
    rows = [r for r in rows if not r.get("synthetic")]
    return HistoryStore().upsert("etf_holdings", rows) if rows else 0


def coverage_table(results: list[Result]) -> str:
    lines = [f"{'etf':7} {'issuer':4} {'source':8} {'date':10} {'n':>4} {'top10':>6}  status"]
    for r in results:
        lines.append(f"{r.etf:7} {r.issuer:4} {r.source or '-':8} {r.asof or '-':10} {r.n:>4} "
                     f"{r.top10:6.3f}  {r.status}{(' (' + r.reason + ')') if r.reason else ''}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch real active-ETF holdings from issuer sites")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--etf", nargs="+")
    ap.add_argument("--history", nargs=2, metavar=("START", "END"),
                    help="also fetch history for issuers that support date queries")
    ap.add_argument("--no-store", action="store_true", help="do not write to data/history")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    etfs = list(REGISTRY) if a.all else [e.upper() for e in a.etf]
    s = _session()
    results = [fetch_one(s, e) for e in etfs]
    n = 0 if a.no_store else store_rows([x for r in results for x in r.rows])
    print(coverage_table(results))
    print(f"\nlatest: stored {n} rows; ok={sum(r.status == 'ok' for r in results)}/{len(results)}")
    if a.history:
        hist: list[Result] = []
        for e in etfs:
            hr = fetch_history(s, e, *a.history)
            got = sorted({r.asof for r in hr if r.asof})
            print(f"history {e}: {len(got)} days {got[:1]}..{got[-1:]}", flush=True)
            hist += hr
            if not a.no_store:
                store_rows([x for r in hr for x in r.rows])
        print(f"history rows: {sum(len(r.rows) for r in hist)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
