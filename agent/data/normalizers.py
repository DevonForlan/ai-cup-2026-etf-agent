"""Parse raw exchange responses into normalized rows.

daily_prices row: date, ticker, market, open, high, low, close, volume, amount, vwap
institutional row: date, ticker, foreign_net, trust_net, dealer_net, total_net (shares)
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

PARSER_VERSION = "norm-v1"


def _num(s) -> Decimal | None:
    if s is None:
        return None
    t = str(s).replace(",", "").strip()
    if t in ("", "--", "---", "X", "除權息", "N/A"):
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def _find_table(j: dict, must_have: list[str]) -> tuple[list[str], list[list]] | None:
    tables = j.get("tables") or []
    if not tables and "fields" in j:
        tables = [j]
    for t in tables:
        fields = [str(f).strip() for f in (t.get("fields") or [])]
        if all(any(m in f for f in fields) for m in must_have):
            return fields, t.get("data") or []
    return None


def _idx(fields: list[str], name: str) -> int:
    for i, f in enumerate(fields):
        if f == name:
            return i
    for i, f in enumerate(fields):
        if name in f:
            return i
    raise KeyError(name)


def _vwap(amount: Decimal | None, volume: Decimal | None) -> Decimal | None:
    if amount is None or volume is None or volume == 0:
        return None
    return amount / volume


def parse_twse_mi_index(content: bytes, date: str, universe: set[str] | None = None) -> list[dict]:
    j = json.loads(content)
    found = _find_table(j, ["證券代號", "成交股數", "成交金額", "收盤價"])
    if not found:
        return []
    fields, data = found
    ic, iv, ia = _idx(fields, "證券代號"), _idx(fields, "成交股數"), _idx(fields, "成交金額")
    io, ih, il, icl = _idx(fields, "開盤價"), _idx(fields, "最高價"), _idx(fields, "最低價"), _idx(fields, "收盤價")
    rows = []
    for r in data:
        t = str(r[ic]).strip()
        if universe is not None and t not in universe:
            continue
        vol, amt = _num(r[iv]), _num(r[ia])
        rows.append(dict(date=date, ticker=t, market="TWSE", open=_num(r[io]), high=_num(r[ih]),
                         low=_num(r[il]), close=_num(r[icl]), volume=vol, amount=amt,
                         vwap=_vwap(amt, vol)))
    return rows


def parse_tpex_daily_quotes(content: bytes, date: str, universe: set[str] | None = None) -> list[dict]:
    j = json.loads(content)
    found = _find_table(j, ["代號", "收盤", "成交股數", "成交金額"])
    if not found:
        return []
    fields, data = found
    ic, icl, io, ih, il = (_idx(fields, "代號"), _idx(fields, "收盤"), _idx(fields, "開盤"),
                           _idx(fields, "最高"), _idx(fields, "最低"))
    iv, ia = _idx(fields, "成交股數"), _idx(fields, "成交金額")
    rows = []
    for r in data:
        t = str(r[ic]).strip()
        if universe is not None and t not in universe:
            continue
        vol, amt = _num(r[iv]), _num(r[ia])
        rows.append(dict(date=date, ticker=t, market="TPEx", open=_num(r[io]), high=_num(r[ih]),
                         low=_num(r[il]), close=_num(r[icl]), volume=vol, amount=amt,
                         vwap=_vwap(amt, vol)))
    return rows


def parse_twse_t86(content: bytes, date: str, universe: set[str] | None = None) -> list[dict]:
    """T86 column positions (verified 2026-10-02): 4 外陸資淨(不含自營), 7 外資自營商淨,
    10 投信淨, 11 自營商淨, 18 三大法人淨。"""
    j = json.loads(content)
    data = j.get("data") or []
    rows = []
    for r in data:
        t = str(r[0]).strip()
        if universe is not None and t not in universe:
            continue
        f1, f2 = _num(r[4]) or 0, _num(r[7]) or 0
        rows.append(dict(date=date, ticker=t, foreign_net=f1 + f2, trust_net=_num(r[10]),
                         dealer_net=_num(r[11]), total_net=_num(r[18])))
    return rows


def parse_tpex_insti(content: bytes, date: str, universe: set[str] | None = None) -> list[dict]:
    """TPEx dailyTrade positions (verified 2026-10-02): 10 外資及陸資合計淨, 13 投信淨,
    22 自營商合計淨, 23 三大法人合計。"""
    j = json.loads(content)
    found = _find_table(j, ["代號", "名稱"])
    if not found:
        return []
    _, data = found
    rows = []
    for r in data:
        t = str(r[0]).strip()
        if universe is not None and t not in universe:
            continue
        if len(r) < 24:
            continue
        rows.append(dict(date=date, ticker=t, foreign_net=_num(r[10]), trust_net=_num(r[13]),
                         dealer_net=_num(r[22]), total_net=_num(r[23])))
    return rows


def parse_finmind_price(content: bytes, market_of: dict[str, str]) -> list[dict]:
    j = json.loads(content)
    rows = []
    for r in j.get("data", []):
        vol, amt = _num(r.get("Trading_Volume")), _num(r.get("Trading_money"))
        t = str(r["stock_id"])
        rows.append(dict(date=r["date"], ticker=t, market=market_of.get(t, "?"),
                         open=_num(r.get("open")), high=_num(r.get("max")), low=_num(r.get("min")),
                         close=_num(r.get("close")), volume=vol, amount=amt, vwap=_vwap(amt, vol)))
    return rows


def parse_finmind_revenue(content: bytes) -> list[dict]:
    j = json.loads(content)
    rows = []
    for r in j.get("data", []):
        rows.append(dict(ticker=str(r["stock_id"]), year=int(r["revenue_year"]),
                         month=int(r["revenue_month"]), revenue=_num(r.get("revenue"))))
    return rows
