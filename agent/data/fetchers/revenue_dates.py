"""Monthly revenue publication dates (published_date / available_at) for table `monthly_revenue`.

Findings (see logs/development/revenue_publication_dates.md):
  * No free official source gives the historical per-company announcement date:
      - MOPS t05st10_ifrs (per company, POST https://mops.twse.com.tw/mops/api/t05st10_ifrs) returns the
        figures and the query time only, no filing date.
      - TWSE OpenAPI t187ap05_L / TPEx mopsfin_t187ap05_O carry one table-wide 出表日期 for the latest
        month only.
      - FinMind TaiwanStockMonthRevenue: `date` = 1st day of the month after the revenue month (not a
        publication date); `create_time` is empty.
  * Usable going forward: the MOPS static summary pages
        https://mopsov.twse.com.tw/nas/t21/{sii|otc}/t21sc03_{rocYear}_{month}_0.html
    are regenerated during the filing window with 出表日期 and list only companies that have filed so
    far. Polling them daily gives a first-seen date = an upper bound of the publication date.

Rules:
  published_date = first MOPS t21sc03 observation date containing the company (upper bound), else NULL.
  available_at   = published_date + 'T23:59:00+08:00' when published_date is known, else
                   placeholder_available_at(): statutory deadline (證交法 §36: by the 10th of the following
                   month; extended to the next business day when the 10th is not one) at 23:59 +08:00.

CLI:
  python agent\\data\\fetchers\\revenue_dates.py                        # recompute available_at only
  python agent\\data\\fetchers\\revenue_dates.py --refetch-finmind --start 2023-01-01 --end 2026-10-02
  python agent\\data\\fetchers\\revenue_dates.py --observe [--ym 2026-09]   # poll MOPS (run daily, days 1-12)
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.data.http import get_bytes, make_session, now_tpe  # noqa: E402
from agent.data.manifest import RAW_DIR, save_raw  # noqa: E402

PARSER_VERSION = "revdate-v1"
DEADLINE_DAY = 10
EOD = "23:59:00"
MOPS_T21SC03 = "https://mopsov.twse.com.tw/nas/t21/{mkt}/t21sc03_{roc}_{m}_0.html"
# Weekday market closures that fall on/after a 10th, used only where the trading calendar is missing.
EXTRA_HOLIDAYS = {"2023-10-09", "2023-10-10", "2024-02-12", "2024-02-13", "2024-02-14",
                  "2024-10-10", "2025-10-10"}


# ----------------------------------------------------------------------------- placeholder (auditable)
def statutory_deadline(year: int, month: int, calendar: list[str] | None = None) -> str:
    """Deadline for revenue of (year, month): the 10th of the following month, rolled forward to the
    next business day when the 10th is a weekend/holiday. Uses the trading calendar when it covers the
    window, else weekday + EXTRA_HOLIDAYS."""
    y, m = (year, month + 1) if month < 12 else (year + 1, 1)
    d = date(y, m, DEADLINE_DAY)
    cal = set(calendar or [])
    lo, hi = (d - timedelta(days=12)).isoformat(), (d + timedelta(days=12)).isoformat()
    covered = any(x < d.isoformat() and x >= lo for x in cal) and any(x > d.isoformat() and x <= hi for x in cal)
    while True:
        s = d.isoformat()
        if covered:
            if s in cal:
                return s
        elif d.weekday() < 5 and s not in EXTRA_HOLIDAYS:
            return s
        d += timedelta(days=1)


def placeholder_available_at(year: int, month: int, calendar: list[str] | None = None) -> str:
    """THE single placeholder rule used when the publication date is unknown."""
    return f"{statutory_deadline(year, month, calendar)}T{EOD}+08:00"


def available_at_for(year: int, month: int, published_date, calendar=None) -> str:
    if isinstance(published_date, str) and published_date:
        return f"{published_date}T{EOD}+08:00"
    return placeholder_available_at(year, month, calendar)


def apply_dates(df: pd.DataFrame, calendar: list[str] | None = None) -> pd.DataFrame:
    """Recompute available_at for every row from published_date / placeholder."""
    out = df.copy()
    pub = out["published_date"].astype("object").where(out["published_date"].notna(), None)
    out["available_at"] = [available_at_for(int(y), int(m), p, calendar)
                           for y, m, p in zip(out["year"], out["month"], pub)]
    return out


# ----------------------------------------------------------------------------- MOPS observation
def parse_mops_t21sc03(content: bytes) -> dict:
    """-> {report_date, year, month, revenue: {ticker: revenue_TWD}} (page amounts are in 千元)."""
    for enc in ("utf-8", "big5", "cp950"):
        try:
            html = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        html = content.decode("cp950", errors="replace")
    txt = re.sub(r"<[^>]+>", "|", html).replace("&nbsp;", " ")
    m = re.search(r"出表日期[:：]\s*(\d{2,3})/(\d{1,2})/(\d{1,2})", txt)
    report = date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))).isoformat() if m else None
    h = re.search(r"(\d{2,3})年(\d{1,2})月份", txt)
    year, month = (int(h.group(1)) + 1911, int(h.group(2))) if h else (None, None)
    rev: dict[str, float] = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        cells = [re.sub(r"<[^>]+>|&nbsp;", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)]
        if len(cells) >= 3 and re.fullmatch(r"\d{4,6}[A-Z]?", cells[0]):
            v = cells[2].replace(",", "")
            try:
                rev[cells[0]] = float(v) * 1000.0
            except ValueError:
                pass
    return dict(report_date=report, year=year, month=month, revenue=rev)


def observe_mops(year: int, month: int, session=None, markets=("sii", "otc"), raw_dir: Path = RAW_DIR) -> list[dict]:
    s = session or make_session()
    obs = []
    for mkt in markets:
        url = MOPS_T21SC03.format(mkt=mkt, roc=year - 1911, m=month)
        b, fetched = get_bytes(s, url, min_interval=3.0, timeout=40, retries=2)
        p = parse_mops_t21sc03(b)
        ts = fetched.isoformat()
        save_raw(fetched.strftime("%Y%m%d"), f"mops_t21sc03_{mkt}", f"t21sc03_{year - 1911}_{month}.html", b,
                 url=url, fetched_at=ts, content_as_of=ts, published_at=p["report_date"], available_at=ts,
                 authority="mops", parser_version=PARSER_VERSION, raw_dir=raw_dir)
        # 出表日期 can lag the fetch; the company was visible no later than the fetch date either way
        seen = min(p["report_date"] or fetched.date().isoformat(), fetched.date().isoformat())
        for t, v in p["revenue"].items():
            obs.append(dict(ticker=t, year=p["year"] or year, month=p["month"] or month, revenue=v, seen=seen))
    return obs


def apply_observations(df: pd.DataFrame, obs: list[dict], universe: set[str] | None = None) -> pd.DataFrame:
    """First-seen wins: never move an existing published_date later. Adds missing rows (revenue from MOPS)."""
    out = df.copy()
    idx = {(str(t), int(y), int(m)): i for i, (t, y, m) in enumerate(zip(out["ticker"], out["year"], out["month"]))}
    new = []
    for o in obs:
        if universe is not None and o["ticker"] not in universe:
            continue
        k = (o["ticker"], int(o["year"]), int(o["month"]))
        if k in idx:
            i = out.index[idx[k]]
            cur = out.at[i, "published_date"]
            if pd.isna(cur) or str(cur) > o["seen"]:
                out.at[i, "published_date"] = o["seen"]
        else:
            new.append(dict(ticker=k[0], year=k[1], month=k[2], revenue=o["revenue"], published_date=o["seen"]))
    if new:
        out = pd.concat([out, pd.DataFrame(new)], ignore_index=True)
    return out


# ----------------------------------------------------------------------------- FinMind refetch
def refetch_finmind(tickers: list[str], start: str, end: str, cfg: dict, session=None) -> list[dict]:
    from agent.data.fetchers import finmind
    s = session or make_session()
    snap = end.replace("-", "")
    rows = []
    for t in tickers:
        try:
            r = finmind.fetch_monthly_revenue(s, cfg, t, start, end, snap)
            rows += r
            print("finmind", t, len(r), flush=True)
        except Exception as e:  # noqa: BLE001
            print("finmind", t, "ERROR", e, flush=True)
    return rows


def main(argv=None):
    from agent.config import load_data_sources, load_universe
    from agent.data.fetchers.corporate_actions import load_calendar
    from agent.data.loaders import HistoryStore

    ap = argparse.ArgumentParser(description="monthly revenue publication dates")
    ap.add_argument("--refetch-finmind", action="store_true")
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--observe", action="store_true", help="poll MOPS t21sc03 summary pages")
    ap.add_argument("--ym", default=None, help="YYYY-MM revenue month to observe (default: previous month)")
    args = ap.parse_args(argv)

    uni = set(load_universe())
    store = HistoryStore()
    cal = load_calendar()
    cur = store.load("monthly_revenue").copy()

    if args.refetch_finmind:
        end = args.end or now_tpe().date().isoformat()
        rows = refetch_finmind(sorted(uni), args.start, end, load_data_sources())
        new = pd.DataFrame(rows)
        if len(new):
            new = new[new["ticker"].isin(uni)]
            keep = cur[["ticker", "year", "month", "published_date"]]
            new = new.merge(keep, on=["ticker", "year", "month"], how="left")
            cur = pd.concat([cur[~cur.set_index(["ticker", "year", "month"]).index.isin(
                new.set_index(["ticker", "year", "month"]).index)], new], ignore_index=True)

    if args.observe:
        if args.ym:
            y, m = (int(x) for x in args.ym.split("-"))
        else:
            t = now_tpe().date().replace(day=1) - timedelta(days=1)
            y, m = t.year, t.month
        obs = observe_mops(y, m)
        print(f"MOPS observed {len(obs)} companies for {y}-{m:02d}; universe hits:",
              sum(o['ticker'] in uni for o in obs))
        cur = apply_observations(cur, obs, uni)

    cur = apply_dates(cur, cal)
    # full rewrite of this table through the store (keys unchanged)
    n = store.upsert("monthly_revenue", cur)
    df = store.load("monthly_revenue")
    print(f"monthly_revenue rows={len(df)} tickers={df['ticker'].nunique()} "
          f"range={df['year'].min()}-{df['month'][df['year'] == df['year'].min()].min():02d}.."
          f"{df['year'].max()}-{df['month'][df['year'] == df['year'].max()].max():02d} "
          f"published_date known={int(df['published_date'].notna().sum())} (upserted {n})")


if __name__ == "__main__":
    main()
