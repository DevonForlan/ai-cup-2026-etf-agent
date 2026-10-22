"""RESEARCH-ONLY data collection: daily per-stock PE / PB / dividend yield published by TWSE (BWIBBU_d) and
TPEx (peQryDate) after each close. Public pages, no login; polite rate limit (>= 2.5 s between requests);
resumable (one raw JSON per market-date). Output: data/research/valuation_daily.parquet (universe only).
Not used by production code.

    .venv\\Scripts\\python.exe research\\factor_research\\fetch_valuation.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
RAW = ROOT / "data" / "research" / "valuation_raw"
OUT = ROOT / "data" / "research" / "valuation_daily.parquet"
UA = {"User-Agent": "Mozilla/5.0 (research; AI CUP 2026 participant; low rate)"}


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return r.read()


def num(x):
    try:
        v = float(str(x).replace(",", "").strip())
        return v
    except ValueError:
        return None


def g(r, ix, k):
    return num(r[ix[k]]) if k in ix else None


def gs(r, ix, k):
    return str(r[ix[k]]).strip() if k in ix else None      # older daily tables have no reported-quarter column


def main() -> int:
    from agent.data.loaders import HistoryStore
    RAW.mkdir(parents=True, exist_ok=True)
    days = sorted(HistoryStore().dates("daily_prices"))
    uni = set(pd.read_csv(ROOT / "config" / "universe_150.csv", dtype=str, encoding="utf-8-sig")["ticker"])
    for d in days:
        y, m, dd = d.split("-")
        for mkt, url in (("twse", f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={y}{m}{dd}&selectType=ALL&response=json"),
                         ("tpex", f"https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate?date={y}%2F{m}%2F{dd}&response=json")):
            f = RAW / f"{mkt}_{d}.json"
            if f.exists() and f.stat().st_size > 100:
                continue
            for attempt in range(3):
                try:
                    f.write_bytes(get(url))
                    break
                except Exception as e:  # noqa: BLE001
                    print(d, mkt, "retry", attempt, type(e).__name__, flush=True)
                    time.sleep(10 * (attempt + 1))
            time.sleep(2.5)
        print(d, flush=True)
    rows = []
    for f in sorted(RAW.glob("*.json")):
        mkt, d = f.stem.split("_", 1)
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if mkt == "twse":
            fields, data = j.get("fields") or [], j.get("data") or []
            ix = {k: fields.index(k) for k in ("證券代號", "殖利率(%)", "本益比", "股價淨值比", "財報年/季") if k in fields}
            for r in data:
                t = str(r[ix["證券代號"]]).strip()
                if t in uni:
                    rows.append((d, t, g(r, ix, "本益比"), g(r, ix, "股價淨值比"), g(r, ix, "殖利率(%)"),
                                 gs(r, ix, "財報年/季")))
        else:
            for tb in j.get("tables") or []:
                fields = tb.get("fields") or []
                if "股票代號" not in fields:
                    continue
                ix = {k: fields.index(k) for k in ("股票代號", "本益比", "殖利率(%)", "股價淨值比", "財報年/季") if k in fields}
                for r in tb.get("data") or []:
                    t = str(r[ix["股票代號"]]).strip()
                    if t in uni:
                        rows.append((d, t, g(r, ix, "本益比"), g(r, ix, "股價淨值比"), g(r, ix, "殖利率(%)"),
                                     gs(r, ix, "財報年/季")))
    df = pd.DataFrame(rows, columns=["date", "ticker", "pe", "pb", "div_yield", "fin_quarter"])
    # published after the close of `date` -> usable for decisions on the NEXT trading day (PIT)
    df["available_at"] = df["date"] + "T18:00:00"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print("rows", len(df), "dates", df["date"].nunique(), "tickers", df["ticker"].nunique())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
