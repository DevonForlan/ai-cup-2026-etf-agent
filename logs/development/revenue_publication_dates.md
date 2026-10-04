# Monthly revenue: publication dates (`published_date` / `available_at`)

Module: `agent/data/fetchers/revenue_dates.py` (tests: `tests/data/test_revenue_dates.py`). Written 2026-10-05.

## What we looked for, and what we found

| Source | Per-company announcement date? | Notes |
|---|---|---|
| FinMind `TaiwanStockMonthRevenue` | No | `date` is always the 1st of the month after the revenue month. `create_time` is empty. |
| MOPS `t05st10_ifrs` (POST `https://mops.twse.com.tw/mops/api/t05st10_ifrs`) | No | Returns the figures and the query timestamp only. |
| MOPS `t51sb10` / `t146sb10` (latest reports / announcements) | No (current only) | Take no date inputs, so they cannot be used for history. |
| TWSE OpenAPI `t187ap05_L`, TPEx `mopsfin_t187ap05_O` | No | One table-wide `出表日期`, latest month only. On 2026-10-05 it still showed 2026-08 data generated 2026-09-17. |
| MOPS static summary `https://mopsov.twse.com.tw/nas/t21/{sii,otc}/t21sc03_{rocY}_{M}_0.html` | **Going forward only** | Regenerated during the filing window with `出表日期`. It lists only the companies that have filed so far, so a daily poll gives a first-seen date (an upper bound of the real date). |

**Conclusion:** we found no free, legal source of the historical per-company filing date. Every month before 2026-09 therefore uses the placeholder rule.

## Rules (in code)

- `placeholder_available_at(year, month)` is the only placeholder rule. It equals `statutory_deadline(...)` + `T23:59:00+08:00`.
  - `statutory_deadline` follows Securities and Exchange Act §36: monthly revenue must be announced by the 10th of the following month. When the 10th is not a business day, the deadline moves to the next business day.
  - Business days come from the `daily_prices` trading calendar where it covers the window. Otherwise the code uses weekdays plus a short list of known closures (10-10, Lunar New Year 2024).
  - This replaces the old fixed "10th 23:59" placeholder. The new value is never earlier: 1,287 rows move to the 11th, 577 to the 12th, 297 to the 13th and 141 to the 15th. Before, those rows could leak 1–5 days when the 10th fell on a weekend or holiday.
- `published_date` is the first date on which MOPS t21sc03 showed the company for that month (`--observe`; first-seen wins and is never moved later). When it is known, `available_at = published_date + T23:59:00+08:00`.

## Coverage (2026-10-05)

- `monthly_revenue`: 6,491 rows, 150 tickers, 2022-12 .. 2026-09. FinMind was refetched from 2023-01-01, 150 calls at 1.5 s.
  - 141 tickers start at 2022-12.
  - 9 later listings start later: 3718, 4749, 4772, 6919, 7734, 7750, 7751, 7769, 7828.
  - `revenue_yoy` for March 2025 windows is now computable.
- `published_date` known for 2 rows: 6510 and 8046, 2026-09 revenue, first seen 2026-10-05. Those 2 rows came from MOPS; MOPS amounts are in thousands of TWD and are stored as TWD.
- Every other row: `published_date` NULL, placeholder `available_at`.

## Remaining uncertainty

1. Many companies (for example 2330) publish between the 1st and the 10th. Using the deadline makes revenue appear up to about 9 days later than reality. This is conservative: no leakage, but some signal lag.
2. Late filers that miss the deadline would leak under the placeholder. They are rare and get exchange sanctions.
3. To start collecting real dates, run `python agent\data\fetchers\revenue_dates.py --observe` daily from the 1st to the 12th of each month. Before 2026-10-27, only 2026-09 revenue (deadline 2026-10-12) can be covered this way.
4. Wayback Machine snapshots of the t21sc03 pages could give partial historical upper bounds. This is not implemented.
