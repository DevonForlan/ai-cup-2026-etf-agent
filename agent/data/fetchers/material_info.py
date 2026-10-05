"""MOPS daily material information (每日重大訊息) -> HistoryStore table `material_info`.

Endpoint (old MOPS site, still served, historical dates back to at least 2024-06):
    POST https://mopsov.twse.com.tw/mops/web/ajax_t05st02
    form: encodeURIComponent=1, step=1, step00=0, firstin=1, off=1, TYPEK=all,
          year=<ROC year>, month=MM, day=DD
Response: UTF-8 HTML, one table for all markets (sii/otc/rotc/pub). Each row shows
發言日期 (ROC, e.g. 114/10/27), 發言時間 (HH:MM:SS), 公司代號, 公司名稱, 主旨 and carries the full
說明 text in hidden inputs h<i>0..h<i>8 (h<i>8 = 說明), so no per-announcement detail request is needed.
The listing for day D also contains announcements of D-1 after 17:30 (page note), so consecutive days
overlap; rows are deduplicated by event_key. Foreign issuers (DR, t59sb01 section) have no hidden body.

PIT: published_at = official 發言日期 + 發言時間 (+08:00); available_at = published_at.

CLI:
  python agent\\data\\fetchers\\material_info.py --dates-from reports\\windows.json --lookback 10 [--windows W5,W1]
  python agent\\data\\fetchers\\material_info.py --start 2025-10-17 --end 2025-11-27
  Sat/Sun are queried by default: the listing for day D holds D-1 after 17:30 plus D, so Friday-evening
  filings only appear in Saturday's listing. --weekdays-only skips them.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.data.http import make_session, now_tpe  # noqa: E402
from agent.data.manifest import RAW_DIR, save_raw  # noqa: E402

PARSER_VERSION = "mi-v1"
URL = "https://mopsov.twse.com.tw/mops/web/ajax_t05st02"
SOURCE = "mops_t05st02"
AUTHORITY = "mops"
MIN_INTERVAL = 5.0
DONE_FILE = RAW_DIR / "material_info_done.json"
UNIVERSE_CSV = ROOT / "config" / "universe_150.csv"

_ROW_RE = re.compile(r"<tr class='(?:even|odd)'>(.*?)</tr>", re.S)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_HID_RE = re.compile(r"<input type='hidden' name='h(\d+)' value='(.*?)'>(?=\s*<input)", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


# ----------------------------------------------------------------------------- helpers
def roc_to_iso(s: str) -> str:
    """'114/10/27' | '1141027' | '20251027' -> '2025-10-27'."""
    s = s.strip().replace("&nbsp;", "").strip()
    if "/" in s:
        y, m, d = (int(x) for x in s.split("/"))
    elif len(s) == 8:
        y, m, d = int(s[:4]), int(s[4:6]), int(s[6:])
    elif len(s) == 7:
        y, m, d = int(s[:3]), int(s[3:5]), int(s[5:])
    else:
        raise ValueError(f"bad date: {s!r}")
    if y < 1911:
        y += 1911
    return f"{y:04d}-{m:02d}-{d:02d}"


def norm_time(s: str) -> str:
    """'17:30:05' | '173005' | '70004' -> 'HH:MM:SS'."""
    s = s.strip().replace("&nbsp;", "").strip()
    if ":" in s:
        h, m, sec = (int(x) for x in s.split(":"))
    else:
        s = s.zfill(6)
        h, m, sec = int(s[:2]), int(s[2:4]), int(s[4:6])
    return f"{h:02d}:{m:02d}:{sec:02d}"


def clean_text(s: str) -> str:
    s = html.unescape(_TAG_RE.sub("", s)).replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in s.strip().split("\n")).strip()


def event_key(ticker: str, published_at: str, subject: str) -> str:
    h = hashlib.sha256(f"{ticker}|{published_at}|{subject}".encode("utf-8")).hexdigest()
    return "sha256:" + h[:32]


def load_universe(path: Path = UNIVERSE_CSV) -> set[str]:
    import csv
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["ticker"].strip() for r in csv.DictReader(f) if r.get("ticker")}


# ----------------------------------------------------------------------------- parsing
def parse_t05st02(content: bytes) -> list[dict]:
    """All announcement rows of one daily listing (any market)."""
    t = content.decode("utf-8", "replace")
    out = []
    for m in _ROW_RE.finditer(t):
        row = m.group(1)
        tds = _TD_RE.findall(row)
        if len(tds) < 5:
            continue
        hid = {}
        for k, v in _HID_RE.findall(row):
            hid[k[-1]] = v                        # name = h<row index><field digit>
        try:
            d = roc_to_iso(clean_text(tds[0]))
            tm = norm_time(clean_text(tds[1]))
        except ValueError:
            continue
        ticker = clean_text(tds[2])
        subject = re.sub(r"\s*\n\s*", " ", clean_text(hid.get("4", tds[4])))   # one-line headline
        tk = re.search(r'TYPEK\.value="(\w+)"', row)
        out.append({
            "ticker": ticker, "name": clean_text(tds[3]), "date": d, "time": tm,
            "published_at": f"{d}T{tm}+08:00", "subject": subject,
            "body": clean_text(hid.get("8", "")), "typek": tk.group(1) if tk else "",
            "fact_date": roc_to_iso(hid["7"]) if hid.get("7", "").strip().isdigit() and len(hid["7"].strip()) == 8 else "",
        })
    return out


def to_records(rows: list[dict], universe: set[str] | None, source_url: str = URL) -> list[dict]:
    recs = {}
    for r in rows:
        if universe is not None and r["ticker"] not in universe:
            continue
        k = event_key(r["ticker"], r["published_at"], r["subject"])
        recs[k] = {"event_key": k, "ticker": r["ticker"], "published_at": r["published_at"],
                   "subject": r["subject"], "body": r["body"], "source": SOURCE,
                   "source_url": source_url, "authority": AUTHORITY, "available_at": r["published_at"]}
    return list(recs.values())


# ----------------------------------------------------------------------------- fetching
_last = [0.0]


def fetch_day(session, d: date, retries: int = 4) -> bytes:
    form = {"encodeURIComponent": "1", "step": "1", "step00": "0", "firstin": "1", "off": "1",
            "TYPEK": "all", "year": str(d.year - 1911), "month": f"{d.month:02d}", "day": f"{d.day:02d}"}
    err = None
    for attempt in range(retries):
        wait = _last[0] + MIN_INTERVAL - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            r = session.post(URL, data=form, timeout=60)
            _last[0] = time.time()
            r.raise_for_status()
            b = r.content
            txt = b.decode("utf-8", "replace")
            if "reportName" not in txt and "查詢無資料" not in txt and "無符合" not in txt:
                raise RuntimeError(f"unexpected page ({len(b)} bytes): {txt[:200]!r}")
            return b
        except Exception as e:  # noqa: BLE001
            _last[0] = time.time()
            err = e
            back = MIN_INTERVAL * (2 ** (attempt + 1))
            print(f"  ! {d} attempt {attempt + 1} failed: {e}; backing off {back:.0f}s", flush=True)
            time.sleep(back)
    raise RuntimeError(f"t05st02 failed for {d}: {err}")


def load_done(path: Path = DONE_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_done(done: dict, path: Path = DONE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(done, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def day_list(start: date, end: date, weekends: bool) -> list[date]:
    out, d = [], start
    while d <= end:
        if weekends or d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def run_range(days: list[date], store, universe: set[str], session, done: dict) -> dict:
    stats = {"dates": 0, "fetched": 0, "all": 0, "universe": 0, "with_body": 0}
    for d in days:
        iso = d.isoformat()
        stats["dates"] += 1
        if iso in done:
            c = done[iso]
            stats["all"] += c.get("all", 0)
            continue
        b = fetch_day(session, d)
        ts = now_tpe().isoformat()
        save_raw(d.strftime("%Y%m%d"), SOURCE, f"t05st02_{d:%Y%m%d}.html.gz", gzip.compress(b), url=URL,
                 fetched_at=ts, content_as_of=iso, available_at=f"{iso}T23:59:59+08:00",
                 authority=AUTHORITY, parser_version=PARSER_VERSION)
        rows = parse_t05st02(b)
        recs = to_records(rows, universe)
        store.upsert("material_info", recs)
        done[iso] = {"all": len(rows), "universe": len(recs),
                     "with_body": sum(1 for r in recs if r["body"]), "fetched_at": ts}
        save_done(done)
        stats["fetched"] += 1
        stats["all"] += len(rows)
        print(f"  {iso}: {len(rows)} rows, {len(recs)} universe", flush=True)
    return stats


def window_stats(store, start: str, end: str) -> dict:
    df = store.load("material_info")
    if not len(df):
        return {"universe_events": 0, "with_body": 0}
    d = df["published_at"].str[:10]
    sub = df[(d >= start) & (d <= end)]
    return {"universe_events": int(len(sub)), "with_body": int((sub["body"].fillna("") != "").sum())}


def main(argv=None) -> int:
    from agent.data.loaders import HistoryStore
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dates-from", help="windows.json with {name: {start, end}}")
    ap.add_argument("--lookback", type=int, default=10, help="calendar days before window start")
    ap.add_argument("--windows", help="comma list of window names (order = fetch order)")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--weekdays-only", action="store_true",
                    help="skip Sat/Sun listings (they hold Fri-after-17:30 and weekend filings)")
    ap.add_argument("--history-dir", help="HistoryStore root (default data/history)")
    a = ap.parse_args(argv)

    jobs: list[tuple[str, date, date]] = []
    if a.dates_from:
        wins = json.loads(Path(a.dates_from).read_text(encoding="utf-8"))
        names = a.windows.split(",") if a.windows else list(wins)
        for n in names:
            w = wins[n]
            jobs.append((n, date.fromisoformat(w["start"]) - timedelta(days=a.lookback),
                         date.fromisoformat(w["end"])))
    if a.start:
        jobs.append(("range", date.fromisoformat(a.start), date.fromisoformat(a.end or a.start)))
    if not jobs:
        ap.error("give --dates-from or --start/--end")

    store = HistoryStore(a.history_dir) if a.history_dir else HistoryStore()
    universe = load_universe()
    session = make_session()
    session.headers["Referer"] = "https://mopsov.twse.com.tw/mops/web/t05st02"
    done = load_done()
    summary = {}
    for name, s, e in jobs:
        print(f"[{name}] {s} .. {e}", flush=True)
        try:
            st = run_range(day_list(s, e, not a.weekdays_only), store, universe, session, done)
        except RuntimeError as ex:
            print(f"[{name}] STOPPED: {ex}", flush=True)
            summary[name] = {"error": str(ex)}
            break
        st.update(window_stats(store, s.isoformat(), e.isoformat()))
        summary[name] = st
        print(f"[{name}] dates={st['dates']} newly_fetched={st['fetched']} all_rows={st['all']} "
              f"universe_events={st['universe_events']} with_body={st['with_body']}", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
