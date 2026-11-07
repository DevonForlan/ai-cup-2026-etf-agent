# TACTICAL_OVERRIDE_V1 — Owner-directed temporary rotation (Issue #43)

Owner directive 2026-11-08 (GitHub Issue #43, "FORCE_TEMPORARY_ROTATION"): reduce technology exposure for **one trading day** and hold a non-tech sleeve from the official 150-name universe, then return. The adverse research (`research/short_rotation/REPORT.md`, branch `research/43-short-rotation`: DO_NOT_ROTATE) stays in the audit trail; the Owner chose the experiment knowingly.

## What it is (and is not)
* A **separate** versioned override: `config/tactical_override_v1.yaml` (fingerprint = sha256 of the file) + `agent/tactical/override.py`.
* Frozen Quant v1 is untouched: `config/strategy_quant_v1.yaml` (sha256 `f34fa02e…`), `agent/features`, `agent/portfolio`, `agent/pipeline.py`, `agent/run_sim.py`, `agent/sim` have **no diff**. The override wraps `agent.pipeline.construct` for one `run_day` call inside `agent/competition_day.py` and always lets the frozen constructor run first.
* Only mode `competition` (scheduled production flow) applies it; `dry-run` / `historical` / simulations never do.

## Behaviour
| trade date | action |
|---|---|
| `entry_trade_date` (2026-11-09) | tech cluster scaled down by x % NAV (ladder 20 → 17 → 14 → 10 → 5 %, first size passing every guard), 6 pre-chosen non-tech names bought equal weight. Goes through the same `_finalize` legality pipeline as every Quant D-Plan (lots, caps, cash band, post-trade compliance, Active Share, stress) plus extra guards: 20–30 names, cash < 25 %, single-name caps, universe membership, official Active Share ≥ 15 %. If no size passes, the **untouched Quant result is returned** (fail closed) and the reason is recorded. |
| `exit_trade_date` (2026-11-10) and every later date | **expiry-first unwind**: if any sleeve name is held above the stored baseline, explicit reverse orders back to the stored pre-rotation lots (derived from the actual holdings, so a missed day, a partial fill or a re-run all work). A failed unwind is recorded as `TACTICAL_UNWIND_OVERDUE`, the Quant result is returned, and the next window retries; the sleeve is never silently extended or reported as unwound. |

2-day alternative: set `hold_trading_days: 2` and `exit_trade_date: '2026-11-11'` in the yaml (re-fingerprinted automatically).

## Rollback
One toggle: delete `config/tactical_override_v1.yaml` or set `enabled: false` (then deploy). Open sleeve positions are still visible to the stored `baseline_holdings`; to unwind anyway keep the file with `entry_trade_date` in the past and `exit_trade_date` = today.

## Evidence
Every activation writes `logs/tactical/<trade_date>_<ENTRY|UNWIND>.json` (version, fingerprint, attempts, sells/buys in shares, tech weight before/after, cash, holdings, Active Share, status, reason) and `summary["tactical_override"]` / `meta["tactical_override"]` in the daily run. `agent/ops/shared_state_tactical.py` (called from `shared_state_sync.sweep`, i.e. after every confirmed submission and every evaluation) publishes them to the `shared-state` branch under `shared_state/tactical/` with the FINAL SHA and the honest submission status (`NOT_CONFIRMED` until the portal evidence exists).

## Selection (as of 2026-11-06 close; no new research)
Eligible non-tech (outside the 7 electronics industries, 120-day correlation to the tech basket ≤ 0.55, ADV20 ≥ 0.5 bn TWD, |1-day move| < 5 %), composite = mean(rank of 5-day relative strength, rank of 60-day volatility, lower is better), ≤ 2 names per industry, top 6, equal weight: 2891 中信金, 2002 中鋼, 2618 長榮航, 5880 合庫金, 5871 中租-KY, 2912 統一超. 2753 / 1476 / 6865 are not in the official universe and are never used.
